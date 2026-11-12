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
    image-inspect  read only (S-03.3; the Owner's decision (e) of 2026-11-10): the stage of
               the profile's provision lock is re-verified as create --provision does, then
               the docker-archive's config and layers are read as data. The gzip layers are
               streamed (each re-hashed against the lock) and applied in order as a union
               view (whiteouts and opaque directories honoured); for each --path: present or
               absent, type, mode, owner, size, the layer that last wrote it, symlink and
               hard-link targets (resolved inside the image root, bounded hops), the sha256
               of the regular file it resolves to, a directory's children and, for
               PATH#key#key, that field of a JSON file; also the config's runtime fields and
               the history lines naming acp, claude, codex or node. Nothing is extracted,
               run or written. Text mode (S-03.3 D-1; the Owner's decision of 2026-11-11),
               every count capped and a reached cap reported: --list GLOB (paths by glob),
               --excerpt PATH START END (lines of a UTF-8 text file), --search GLOB REGEX
               (matches with --context bytes around them, at most --max-matches per file),
               --distinct GLOB REGEX (distinct matched values with counts) and, for
               EXE!MODULEGLOB, the PYZ modules of a PyInstaller executable: listed, searched
               after a bounded inflate, or --strings (each code object's string constants and
               names, the marshal data walked as data, never loaded). Binary or oversized
               content is reported, never dumped.
    provision  guest side of provisioning (F-04.1b; decision 0006): for an instance made
               with create --provision (whose seed carries the manifest of the verified
               stage and the single-use root step), re-verify the stage, SFTP the .deb
               files, the image archive and the release binary into the agent-owned
               upload directory within provisioning.upload's bounds, check each in the
               guest, create the READY marker, wait on the root step's RESULT.json (an
               inotify event, under a ceiling), fetch it and check it. The root step
               copies, verifies, installs Moby with apt from the local files, docker
               loads the image, checks its ID, keeps only the local immutable tag, runs it
               once, installs and starts the OpenHands Agent Server under the no-login
               user openhands with its two guest-generated secrets (F-04.1 slice (c)),
               deletes the upload and disables itself; provision then fetches the session
               API key alone into the instance directory. No network at any point.
    conversation-smoke  the disposable Docker conversation (F-04.2) on a running provisioned
               instance: the pinned fixture (and, with --openapi, its schema check), the
               lifecycle routes in the server's own OpenAPI document, create (a non-2xx is a
               refusal and stops the run), the conversation and its container (on-demand
               root facts: image ID, exact mounts, user, caps, the 127.0.0.1 port and its
               docker-proxy listener, profiles P7 as amended), an idempotent second create,
               the events (API and disk), inspect with it running, stop of its runtime,
               reopen (same id, state, events and mounts), with --restart a guest stop and
               start and a second reopen, then delete. API calls run as agent on the guest
               loopback with the session key read from its file; no LLM, no message.
    admission-probe, job-access-probe  the management API admission (S-01.3.1) and the
               job environment (S-01.3.2) from inside two disposable conversation
               containers; job-access-probe also runs the predeclared egress sweep of S-01.4
               (public literals, SLIRP's aliases, an unconfigured guestfwd-class address)
               against the egress guard's counters.
    containment-probe  S-02.1: the versioned containment catalogue
               (security/containment-cases.json) in one pass: admission-probe and
               job-access-probe unchanged, the remaining cases inside two further disposable
               conversation containers with generated canary workspaces; per case the
               attempt, principal, observations, control result and verdict (PASS, FAIL,
               UNKNOWN) with the runtime-configuration snapshot; --sensitivity also runs
               the catalogue's mutations, which must classify as FAIL.
    drill      E-01.2.2 slice (b), TEST ONLY, on an instance made with create --provision
               --drill (whose seed also carries tools/guest_drill.py, a root helper that acts
               on agent's requests): fail-closed (a bad key check and a failing guard each
               stop the chain, then are restored), stored-state (every field of the
               job-writable stored conversation state altered alone, then a server restart
               and a reopen; the container must not change), root-scan (the guest-root P5
               scan), f2-closed (slice (c): the quiesce step neutralizes job-written stored
               state before every server start; variants A to G with a fixed decision
               rule). containment-probe --drill-defective-control runs there only.
    host-census  S-01.4: a read-only, unelevated census of the harness's host listeners by
               PID (QEMU, Gitea, the Owner host's Vite servers; each must be on 127.0.0.1)
               and the Windows Firewall profiles and rule count, recorded as disclosure.
               It needs no profile or state directory and changes nothing.

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
    python -I -B tools/guest.py host-census [--exclude-pid PID ...] [--out FILE]
    python -I -B tools/guest.py check-surfaces --profile PROFILE --state-dir STATE --name NAME
                                          --canaries DIR
    python -I -B tools/guest.py netprobe  --profile PROFILE --state-dir STATE --name NAME
    python -I -B tools/guest.py smoke     --profile PROFILE --state-dir STATE --name NAME
                                          --canaries DIR --durable DIR [--durable DIR ...]
                                          [--out FILE]
    python -I -B tools/guest.py provision-fetch --profile PROFILE --state-dir STATE
    python -I -B tools/guest.py image-inspect --profile PROFILE --state-dir STATE
                                          [--path PATH[#key#key] ...] [--list GLOB ...]
                                          [--excerpt PATH START END ...]
                                          [--search GLOB REGEX ...] [--distinct GLOB REGEX ...]
                                          [--strings EXE!MODULEGLOB ...] [--context BYTES]
                                          [--max-matches N]
    python -I -B tools/guest.py create    --profile PROFILE --state-dir STATE --name NAME --provision
    python -I -B tools/guest.py provision --profile PROFILE --state-dir STATE --name NAME
    python -I -B tools/guest.py conversation-smoke --profile PROFILE --state-dir STATE --name NAME
                                          [--restart] [--openapi FILE] [--canaries DIR] [--out FILE]
    python -I -B tools/guest.py containment-probe --profile PROFILE --state-dir STATE --name NAME
                                          [--sensitivity] [--token-fingerprint L=sha256:H] [--out FILE]
    python -I -B tools/guest.py create    --profile PROFILE --state-dir STATE --name NAME --provision --drill
    python -I -B tools/guest.py drill     --profile PROFILE --state-dir STATE --name NAME
                                          --kind fail-closed|stored-state|root-scan|f2-closed
                                          [--canaries DIR] [--raw] [--limit N] [--out FILE]
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
import fnmatch
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
import struct
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _load_repository_access():
    """The shared repository-access module (integrations/repository, decision 0014), loaded by
    path once per process: the standard library at import, Dulwich only when a repository is
    opened (CannotRun REPOSITORY_NEEDS_DULWICH without it)."""
    module = sys.modules.get('repository_access')
    if module is None:
        path = REPO / 'integrations' / 'repository' / 'repository_access.py'
        spec = importlib.util.spec_from_file_location('repository_access', path)
        module = importlib.util.module_from_spec(spec)
        sys.modules['repository_access'] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            del sys.modules['repository_access']
            raise
    return module


def _no_window():
    """integrations/platform/no_window.py, the shared no-window helper, loaded by path once per process:
    ``_no_window().no_window_flags()`` is CREATE_NO_WINDOW only where this process has no console."""
    module = sys.modules.get('aieh_no_window')
    if module is None:
        spec = importlib.util.spec_from_file_location(
            'aieh_no_window', REPO / 'integrations' / 'platform' / 'no_window.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        sys.modules['aieh_no_window'] = module
    return module


repository_access = _load_repository_access()
INVENTORY_FORMAT = 'repo-inventory/2'
LAUNCH_SCHEMA = 'ai-engineering-harness/profiles/launch-record/v1'
INSPECT_SCHEMA = 'ai-engineering-harness/profiles/inspect-record/v1'
SMOKE_SCHEMA = 'ai-engineering-harness/profiles/smoke-record/v1'
LOG_HEADER_SCHEMA = 'ai-engineering-harness/profiles/log-header/v1'
LOG_HEADER_PREFIX = 'AIEH-LOG-HEADER '
# profiles P11: the label fields and their allowed values
LABEL_VALUES = {'tier': ('strong', 'trusted-workload'), 'nesting': ('none', 'nested')}
LOOPBACK = '127.0.0.1'
GUEST_USER_HOST = '127.0.0.1'
# The long-lived background starts (QEMU, the inference forward holder) carry this flag unconditionally:
# a console process started with it gets a console that no window shows, and its children share it (0
# elsewhere). Every other launch passes _no_window().no_window_flags(), which is this flag only where this
# process has no console (integrations/platform/no_window.py); exec, an interactive passthrough, shares the
# operator's console. Never DETACHED_PROCESS, under which every console child opens a window of its own (the
# Owner's rule of 2026-11-11; tools/tests/test_launch_census.py checks every launch).
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
# The guest login the SSH channel runs as unless told otherwise: GuestApi's, so the login that reads the
# management key and the dispatcher's guest login during bootstrap (decision 0013 point 1; E-01.3.3).
GUEST_API_LOGIN = 'agent'
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
    # One json.dumps and one write: json.dump with indent runs the pure-Python encoder and hands
    # the file each small chunk in turn (plan leaf F-09); the bytes are the same.
    with open(path, 'x', encoding='utf-8', newline='\n') as handle:
        handle.write(json.dumps(data, indent=2, sort_keys=True) + '\n')


def write_stamped_record(records, operation, data):
    """Write data to records/OPERATION-STAMP.json, STAMP being the UTC time to the
    microsecond (%Y%m%dT%H%M%S%fZ), by exclusive create: a record is never overwritten.

    The clock's effective resolution is coarser than a microsecond (about 1 ms, and up to
    15.625 ms, on Windows CPython 3.12), so two records of one operation can read the same
    instant. When the name exists, the stamp advances by one microsecond and the create is
    retried until it succeeds. Every name keeps its shape and the names of an operation
    sort in write order (unless more records are written within one clock tick than the
    tick has microseconds)."""
    records = Path(records)
    records.mkdir(exist_ok=True)
    when = datetime.now(timezone.utc)
    while True:
        path = records / f'{operation}-{when.strftime("%Y%m%dT%H%M%S%fZ")}.json'
        try:
            write_json_exclusive(path, data)
            return path
        except FileExistsError:
            when += timedelta(microseconds=1)


def write_record(instance_dir, operation, data):
    return str(write_stamped_record(Path(instance_dir) / 'records', operation, data))


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
                        inputs, argv, env, disk_commands, validation=None, provisioning=None,
                        inference=None):
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
    if inference is not None:
        record['inference'] = inference      # decision 0015: the opt-in composition
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
    """The checkout's HEAD; refuse when profiles/ has uncommitted changes (tracked or untracked),
    as ``git rev-parse HEAD`` and ``git status --porcelain --untracked-files=all -- profiles``
    answer. Read in process by the shared repository-access module under the ``host``
    configuration policy (decision 0014 sections 1 and 5, row R7: the configuration git would
    read for this checkout, recorded in ``config_sources``); a status the module cannot give as
    git does (ATTRIBUTES_UNSUPPORTED, FILTER_UNSUPPORTED) refuses."""
    ra = repository_access
    try:
        with ra.open_repository(repo, config='host') as opened:
            head = opened.head().commit
            dirty = opened.status(['profiles'], 'all') if head is not None else []
            sources = [posix(source) for source in opened.config_sources]
    except (ra.RepositoryError, ra.CannotRun) as exc:
        raise Refused('REFUSED', f'{repo}: the profile revision cannot be read: {exc.code}: '
                      f'{exc.message}') from None
    if head is None:
        raise Refused('REFUSED', f'{repo}: HEAD names no commit')
    if dirty:
        raise Refused('REFUSED', 'profiles/ has uncommitted changes; create records the '
                      'profile revision and refuses a dirty profile',
                      [f'{entry.xy} {entry.path}' for entry in dirty])
    return {'kind': 'git-revision', 'head': head, 'profiles_clean': True, 'config_policy': 'host',
            'config_sources': sources}


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
                                text=True, check=False, creationflags=_no_window().no_window_flags())
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

    def run(self, command, user=GUEST_API_LOGIN, input_text=None, timeout=300):
        result = self.run_raw(command, user, input_text, timeout)
        return subprocess.CompletedProcess(
            result.args, result.returncode,
            result.stdout.decode('utf-8', errors='replace').replace('\r\n', '\n'),
            result.stderr)

    def run_raw(self, command, user=GUEST_API_LOGIN, input_text=None, timeout=300):
        """stdout as bytes (for example a tar stream); stderr decoded."""
        # Bytes, not text mode: on Windows a text-mode pipe writes '\r\n' for '\n', and the
        # guest's bash would read '{\r' instead of '{'.
        data = input_text.encode('utf-8') if input_text is not None else None
        result = subprocess.run(self.argv(user, command), input=data, capture_output=True,
                                timeout=timeout, check=False, creationflags=_no_window().no_window_flags())
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
                                    stdin=subprocess.DEVNULL, timeout=timeout, check=False,
                                    creationflags=_no_window().no_window_flags())
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


# The host git serves the exchange verifier alone (verify_pulled_bundle, row R6 of decision
# 0014): git stays the integrity authority of bundles pulled from the guest (section 7).


def git_binary():
    path = shutil.which('git')
    if not path:
        raise Refused('REFUSED', 'git not found on PATH (the exchange verifies pulled bundles '
                      'with the host git)')
    return path


def git_env(home):
    """git without system or global configuration, prompts or the caller's environment."""
    env = {key: os.environ[key] for key in ('SYSTEMROOT', 'WINDIR', 'SYSTEMDRIVE', 'PATH')
           if key in os.environ}
    env.update({'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
                'GIT_TERMINAL_PROMPT': '0', 'GIT_ATTR_NOSYSTEM': '1', 'HOME': str(home)})
    return env


def run_git(args, home, repo=None, timeout=600):
    # core.longpaths: the exchange's verify repositories sit deep below the state directory;
    # without it Git for Windows cannot create or read paths of 260 characters or more.
    argv = [git_binary(), '-c', f'core.hooksPath={os.devnull}', '-c', 'core.fsmonitor=false',
            '-c', 'core.longpaths=true']
    if repo is not None:
        argv += ['-C', str(repo)]
    result = subprocess.run(argv + list(args), capture_output=True, env=git_env(home),
                            stdin=subprocess.DEVNULL, timeout=timeout, check=False,
                            creationflags=_no_window().no_window_flags())
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


def parse_bundle_header(path):
    """The header of a git bundle file (gitformat-bundle): version, capabilities, prerequisites,
    references and where the pack starts; anything else is refused (BUNDLE). The shared
    module's parser (decision 0014 section 8), with this tool's refusal."""
    try:
        return repository_access.parse_bundle_header(path)
    except repository_access.RepositoryError as exc:
        raise Refused('BUNDLE', exc.message) from None


def pack_trailer(path, header):
    """The bundle's packfile checksum, recomputed (the shared module's ``pack_trailer``): the
    pack starts with 'PACK' after the header and ends with the hash of everything before the
    trailer (SHA-1, or SHA-256 when the v3 header says object-format=sha256)."""
    return repository_access.pack_trailer(path, header)


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


def count_commits(opened, commit, limit):
    """The commits reachable from COMMIT (``git rev-list --count``), walked through the module's
    ``<commit>^<n>`` parents; the walk stops once it passes LIMIT (the count is then LIMIT + 1)."""
    seen, stack = set(), [commit]
    while stack and len(seen) <= limit:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        number = 1
        while (parent := opened.commit(f'{current}^{number}')) is not None:
            stack.append(parent)
            number += 1
    return len(seen)


def exchange_push(ctx, name, repo, ref, bundle_name=None):
    """exchange push: one local branch as a complete git bundle, bounded and verified.

    The bundle is written in process by the shared repository-access module (decision 0014
    row R5, ``write_bundle``) under the ``repository`` configuration policy; no git is launched.
    The branch resolves as ``git rev-parse --verify --quiet --symbolic-full-name`` (``full_name``)
    and must be one refs/heads/ branch; its header (exactly that branch at its commit, no
    prerequisites), the bounds and the recomputed pack trailer are checked here, in Python.
    The pulled side keeps git as the integrity authority (``verify_pulled_bundle``)."""
    t0 = time.time()
    ra = repository_access
    idir, record = running_instance(ctx, name)
    ex = exchange_config(ctx.profile)
    bounds = ex.get('push') or {}
    outbound = staging_dir(ctx, name, 'outbound')
    repo = Path(repo).resolve()
    if inside(repo, ctx.state_dir):
        raise Refused('REFUSED', f'{repo} is inside the state directory')
    if not isinstance(ref, str) or not ref or ref.startswith('-'):
        raise Refused('REFUSED', f'{ref!r} is not a branch name')
    try:
        opened = ra.open_repository(repo, config='repository', work_tree=False)
    except ra.CannotRun as exc:
        raise Refused('EXCHANGE', f'{repo}: not a git repository; {exc.code}: {exc.message}') from None
    except ra.RepositoryError as exc:
        raise Refused('EXCHANGE', f'{repo}: {exc.code}: {exc.message}') from None
    with opened:
        try:
            full = opened.full_name(ref) or ''
        except ra.RepositoryError as exc:
            raise Refused('REFUSED', f'{ref!r} is not a branch name ({exc.code})') from None
        if not re.fullmatch(r'refs/heads/[^\s]+', full):
            raise Refused('REFUSED', f'{ref!r} is not a local branch (resolved to {full!r}); '
                          'exchange push sends exactly one refs/heads/ branch')
        try:
            commit = opened.commit(full)
            if commit is None:
                raise Refused('EXCHANGE', f'{full} names no commit')
            limit = bounds.get('max_commits', 0)
            commits = count_commits(opened, commit, limit)
            if commits > limit:
                raise Refused('BOUNDS', f'{full} has more than {limit} commits; '
                              f'exchange.push.max_commits is {bounds.get("max_commits")}')
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dt%H%M%Sz')
            bname = check_exchange_name(bundle_name or f'{name}-{stamp}-{commit[:12]}.bundle',
                                        bounds.get('name_pattern', r'^$'), 'bundle name')
            local = outbound / bname
            if os.path.lexists(local):
                raise Refused('REFUSED', f'{local} exists; a bundle is never overwritten')
            opened.write_bundle([full], local)
            sources = [posix(source) for source in opened.config_sources]
        except ra.RepositoryError as exc:
            raise Refused('EXCHANGE', f'{repo}: {exc.code}: {exc.message}') from None
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
              'source': {'ref': full, 'commit': commit, 'commits': commits,
                         'config_policy': 'repository', 'config_sources': sources},
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
    refs/pulled/ and checks each one (``rev-parse --verify``), then ``git fsck --strict``.

    Git stays the integrity authority here (decision 0014 section 7, row R6): Dulwich has no
    strict or connectivity fsck (hard gap G6; its ``porcelain.fsck`` checks objects one by one
    and crashed on a corrupt pack) and no ``bundle verify`` (G7). Every git step above is kept,
    in this order; a Dulwich walk may only be added before or after them, never instead of one.
    ``run_git`` and ``git_env`` serve this verifier alone.
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
                                env=scrubbed_env(ctx.values), check=False, timeout=60,
                                creationflags=_no_window().no_window_flags())
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
    """Re-check every input digest, then start QEMU detached and wait for QMP.

    Detached means: in its own process group, with a console of its own that no window shows
    (CREATE_NO_WINDOW), so it is outside the caller's console and outlives the caller as before;
    it is stopped over QMP or by TerminateProcess (stop, force_stop), never by a console event."""
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
                                creationflags=NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
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
                                  check=False, creationflags=_no_window().no_window_flags())
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
           provision=False, egress_falsification=False, drill=False, drill_leaf=None,
           inference=False):
    """The create binding. ``netprobe`` is set only by the netprobe operation (a
    NetprobeSession); the ordinary create takes no validation input. ``provision`` (F-04.1)
    writes the provisioning manifest of the verified host stage into the seed; the
    provision operation then transfers the files and the seeded root step installs them.
    ``egress_falsification`` (S-01.4 fix-forward, with ``provision`` only) marks the manifest
    so that the root step enables the route-present falsification request
    (job-access-probe); an ordinary provisioned guest never has it. ``drill`` (E-01.2.2
    slice (b), with ``provision`` only) seeds the TEST-ONLY drill helper as a second
    user-data part and records a drill validation block naming ``drill_leaf``, the plan
    leaf the guest is created for (one of DRILL_LEAVES); an ordinary create never does.
    ``inference`` (decision 0015, with ``provision`` only, never a drill or validation
    instance) applies the opt-in inference composition: the profile's pinned seed overlay
    (sshd forwarding directives, the container guard's one ACCEPT, the boot facts' sshd -T)
    and the composition's daemon.json keys in the manifest; the launch record gains an
    inference block. Without it the seed and the manifest are the ordinary ones."""
    if inference and (not provision or drill or netprobe is not None):
        raise Refused('REFUSED', '--inference needs --provision and is never a drill or '
                      'validation instance')
    if egress_falsification and not provision:
        raise Refused('REFUSED', '--egress-falsification needs --provision')
    if drill and (not provision or netprobe is not None):
        raise Refused('REFUSED', '--drill needs --provision and is never a netprobe instance')
    if drill and drill_leaf not in DRILL_LEAVES:
        raise Refused('REFUSED', f'--drill needs --drill-leaf, one of {", ".join(DRILL_LEAVES)}: '
                      'the plan leaf whose drills the guest is for')
    if drill_leaf is not None and not drill:
        raise Refused('REFUSED', '--drill-leaf needs --drill')
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
    manifest = build_provision_manifest(ctx, egress_falsification, inference) if provision \
        else None
    instances = idir.parent
    if not instances.is_dir():
        os.mkdir(instances)
    os.mkdir(idir)            # fails if it appeared meanwhile: never reused
    os.mkdir(idir / 'ssh')
    log(f'create: {idir}')
    keygen = subprocess.run([openssh('ssh-keygen.exe'), '-q', '-t', 'ed25519', '-N', '', '-C',
                             name, '-f', str(idir / 'ssh' / 'id_ed25519')],
                            capture_output=True, text=True, check=False, timeout=60,
                            creationflags=_no_window().no_window_flags())
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
                                timeout=120, creationflags=_no_window().no_window_flags())
        disks[disk] = {'argv': argv, 'rc': result.returncode, 'stdout': result.stdout.strip(),
                       'stderr': result.stderr.strip()}
        if result.returncode != 0:
            raise Refused('REFUSED', f'qemu-img for {disk} failed: {result.stderr.strip()}')
    if drill:
        script = drill_script(ctx.repo)
        seed = drill_seed(ctx.profile_path, idir, name, idir / 'ssh' / 'id_ed25519.pub', script,
                          manifest['bytes'])
        ssh_port, qmp_port = allocate_ports(2)
    elif netprobe is None:
        gen = load_seed_generator()
        try:
            seed = gen.generate(str(ctx.profile_path.parent), str(idir), name,
                                str(idir / 'ssh' / 'id_ed25519.pub'),
                                provision_manifest=manifest['bytes'] if manifest else None,
                                compositions=('inference',) if inference else ())
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
    elif drill:
        validation = drill_validation(script, seed['validation'], drill_leaf)
    provisioning = None
    if manifest is not None:
        if seed.get('provision_manifest_sha256') != manifest['sha256']:
            raise Refused('REFUSED', 'seed: the provisioning manifest digest differs')
        provisioning = manifest['record']
    record = build_launch_record(ctx.profile, ctx.profile_path, values, name,
                                 seed['instance_id'], ports, revision, inputs, argv, env,
                                 disk_commands, validation, provisioning,
                                 inference_record(ctx.profile, seed) if inference else None)
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
    if record.get('inference'):
        result['inference'] = record['inference']
    if planted:
        result['canaries'] = {'planted_in_environment': planted,
                              'needles': canary_summary(canaries['needles'])}
    if validation is not None:
        result['validation'] = {k: validation.get(k) for k in ('mode', 'argv_changes', 'guestfwd',
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
    if record.get('validation') and record['validation'].get('mode') != 'drill':
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
    forward = forward_state(ctx.profile, idir)
    if forward['held']:                    # decision 0015 section 4.4: the forward ends with the guest
        result['inference_forward'] = forward_stop(ctx.profile, idir, forward)
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


def recreate_inference(ctx, name, provision):
    """Whether recreate carries the inference composition: an instance created with --inference is
    recreated with it (decision 0015: never dropped silently), which needs --provision; an instance
    without a launch record (absent) carries nothing. Read before destroy."""
    path = Path(ctx.instance_dir(name)) / 'launch.json'
    if not path.is_file():
        return False
    try:
        record = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise Refused('REFUSED', f'{path}: cannot read the launch record ({exc}); recreate does '
                      'not drop a composition it cannot see') from None
    if not isinstance(record, dict) or not inference_opted(record):
        return False
    if not provision:
        raise Refused('REFUSED', f'{name} was created with create --provision --inference: recreate '
                      'carries the inference composition and needs --provision')
    return True


def recreate(ctx, name, ready_timeout=READY_TIMEOUT_S, canaries=None, provision=False):
    """destroy, then create with the same name and profile (with --provision, the new
    instance carries the provisioning manifest again; the provision operation follows). The
    inference composition is carried from the launch record (recreate_inference); the
    --egress-falsification mark is not (a test aid, dropped as before)."""
    inference = recreate_inference(ctx, name, provision)
    destroyed = destroy(ctx, name)
    created = create(ctx, name, ready_timeout, canaries, provision=True, inference=inference) \
        if provision else create(ctx, name, ready_timeout, canaries)
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
    # The one launch without CREATE_NO_WINDOW (tools/tests/test_launch_census.py, WINDOW_ALLOWLIST): an
    # interactive passthrough, ssh shares the operator's console and opens no window of its own; with
    # CREATE_NO_WINDOW it would have a console of its own and could not reach the operator's.
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


# A secret-shaped run (a provider API key among them): searched by its fingerprint only
TOKEN_RUN = re.compile(rb'(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{20,512}(?![A-Za-z0-9_-])')


def token_fingerprint(value):
    """The reports' fingerprint of a secret (integrations/platform contract.fingerprint):
    sha256:<the first 16 hex digits of the sha256 of its UTF-8 bytes>."""
    return 'sha256:' + hashlib.sha256(value).hexdigest()[:16]


def scan_bytes(data, literals, patterns, fingerprints=None):
    """Labels of the literals and pattern classes found in one byte string; with
    ``fingerprints`` ({label: {fingerprint, ...}}), also the labels whose fingerprint a
    secret-shaped run of the data has (the value itself is never known here)."""
    found = {label for label, needle in literals if needle in data}
    for label, regexes in patterns.items():
        if any(re.search(rx, data) for rx in regexes):
            found.add(label)
    if fingerprints:
        runs = {token_fingerprint(m.group(0)) for m in TOKEN_RUN.finditer(data)}
        found.update(label for label, fps in fingerprints.items() if runs & set(fps))
    return found


def scan_tar(tar_bytes, literals, patterns, fingerprints=None):
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
            for label in sorted(scan_bytes(data, literals, patterns, fingerprints)):
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
           'owner_hits': [], 'canary_hits': [], 'key_hits': [], 'provider_key_hits': []}
    for source, hits in [('guest', scan['hits'])] + [(f'host:{k}', v) for k, v in host_scans.items()]:
        for hit in hits:
            label, where = hit['label'], f'{source}:{hit.get("member", "")}'
            if source == 'guest' and hit['member'] == control_member:
                continue
            if label.startswith('canary:'):
                out['canary_hits'].append({'label': label, 'where': where})
            elif label == 'instance-private-key':
                out['key_hits'].append({'where': where})
            elif label == 'provider-key':
                out['provider_key_hits'].append({'where': where})
            elif label.startswith('owner:'):
                out['owner_hits'].append({'class': owner_class(label), 'where': where})
    return out


def scan_host_file(path, literals, patterns, owner=True, fingerprints=None):
    data = Path(path).read_bytes()
    use = [(lab, n) for lab, n in literals if owner or not lab.startswith('owner:')]
    pats = patterns if owner else {}
    return [{'label': lab, 'member': Path(path).name}
            for lab in sorted(scan_bytes(data, use, pats, fingerprints))]


def collect_p5(ssh, idir, record, canaries, secret_scan=None, provider_key_fingerprint=None,
               provider_key_search=None):
    """The P5 test: plant the positive control, collect, remove it, scan on the host.

    Canary values never travel to the guest: the guest's data comes to the host and is
    searched here. The control file holds synthetic samples of each Owner class only.
    ``provider_key_fingerprint`` (decision 0015 section 4.5) makes the provider key a
    needle by its fingerprint: every secret-shaped run is fingerprinted and compared.
    ``provider_key_search(tar bytes, {label: host path})`` (S-03.2's proof as amended)
    searches the collection and the host files for the synthetic key itself, raw and
    encoded, on the host, in memory (provider_key_search below); the key never travels to
    the guest either.
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
    fingerprints = {'provider-key': {provider_key_fingerprint}} \
        if provider_key_fingerprint else None
    out['provider_key'] = {'fingerprint': provider_key_fingerprint}
    try:
        scan = scan_tar(collected.stdout, literals, patterns, fingerprints)
        names = tar_member_names(collected.stdout)
        if secret_scan is not None:          # F-04.1: the Agent Server secrets (counts only)
            out['agent_server_secrets'] = secret_scan(collected.stdout)
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
        host_scans[key] = scan_host_file(path, literals, patterns, owner=key != 'launch.json',
                                         fingerprints=fingerprints)
    out['host_files'] = sorted(host)
    if provider_key_search is not None:
        out['provider_key_search'] = provider_key_search(collected.stdout, host)
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
                                check=False, timeout=60, creationflags=_no_window().no_window_flags())
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
                            capture_output=True, text=True, check=False, timeout=120,
                            creationflags=_no_window().no_window_flags())
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
        ('storage_dirs', f'for d in {dirs}; do printf "%s|%s\\n" "$(stat -c \'%n|%U|%G|%a|%F\' -- "$d")" '
                         '"$(findmnt -n -o TARGET --target "$d")"; done' if dirs else 'echo none'),
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
    fingerprint = (p5.get('provider_key') or {}).get('fingerprint')
    if inference_opted(record) or fingerprint:
        # decision 0015 section 4.5: the provider key's fingerprint is a P5 needle; without
        # one (inspect --provider-key-fingerprint) the check is UNKNOWN
        checks.append(check(INFERENCE_KEY_CHECK, {'needle': fingerprint, 'hits': []},
                            None if not fingerprint else summary.get('provider_key_hits'),
                            'host: every secret-shaped run of the collection, seed.iso, '
                            'launch.json and serial.log, fingerprinted',
                            None if not fingerprint else not summary.get('provider_key_hits')))
    search = p5.get('provider_key_search')
    if inference_opted(record) or search is not None:
        # S-03.2's proof as amended: the fingerprint alone is not proof that the raw key is absent;
        # without the search of the key itself (inspect --provider-key-stdin) this check is UNKNOWN,
        # and so is an incomplete or invalid search
        verdict = (search or {}).get('verdict')
        checks.append(check(INFERENCE_KEY_SEARCH_CHECK, {'verdict': 'not-found', 'controls': 'valid'},
                            None if search is None else key_search_summary(search),
                            'host: the synthetic key held in memory (inspect --provider-key-stdin), '
                            'raw and in its encodings, over the collection, seed.iso, launch.json '
                            'and serial.log, with positive controls (inference_key_search.py)',
                            None if verdict not in ('found', 'not-found') else verdict == 'not-found'))
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
    agent = agent_server_checks(profile, record, obs) if record.get('provisioning') else {}
    inference = inference_checks(profile, record, obs)
    props.append(prop('P5', p5_checks(record, obs) + agent.get('P5', []), formal=formal, note=(
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
        (moby_p7_checks(obs, profile, record) if record.get('provisioning') else []) +
        agent.get('P7', []) +
        inference['P7'],
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
        props.append(provisioning_property(profile, record, obs, agent.get('provisioning', []) +
                                           admission_check(profile, obs, record) +
                                           quiesce_check(profile, obs) +
                                           start_check(profile, obs)))
    return props


def inspect(ctx, name, canaries=None, provider_key_fingerprint=None, provider_key=None):
    """The P1-P12 record. ``canaries`` is a loaded canary set (load_canaries) or None;
    without it the P5 canary check is UNKNOWN. ``provider_key_fingerprint`` (sha256:<16 hex>,
    decision 0015) adds the provider key as a P5 needle; for an instance with the inference
    composition its check is UNKNOWN without one. ``provider_key`` (S-03.2: the synthetic
    qualification key, read from standard input, the key of that fingerprint) adds the search
    for the key itself (provider_key_search); for such an instance that check is UNKNOWN
    without it."""
    if provider_key_fingerprint is not None and \
            not GITEA_FINGERPRINT.match(str(provider_key_fingerprint)):
        raise Refused('REFUSED', '--provider-key-fingerprint: sha256:<16 hex digits>')
    guard = None
    if provider_key is not None:
        ks = key_search()
        try:
            ks.check_fingerprint(provider_key, provider_key_fingerprint)
            guard = ks.Search(provider_key)
        except ks.SearchError as exc:
            raise Refused('REFUSED', f'--provider-key-stdin: {exc}') from None
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
    p5_scan = None
    if record.get('provisioning'):
        custody = idir / 'agent-server' / 'session.key'
        session_key = custody.read_bytes().strip() if custody.is_file() else None
        facts = _probe_json(obs, 'moby_facts') or {}
        secret_fp = ((((facts.get('agent_server') or {}).get('secrets') or {})
                      .get('fingerprints') or {}).get('OH_SECRET_KEY'))
        obs['agent_server_custody'] = {
            'present': custody.is_file(),
            'host_fingerprint': secret_fingerprint(session_key) if session_key else None}

        def p5_scan(tar_bytes):
            return tar_secret_scan(tar_bytes, session_key, secret_fp)
    obs['p5'] = collect_p5(ssh, idir, record, canaries, secret_scan=p5_scan,
                           provider_key_fingerprint=provider_key_fingerprint,
                           provider_key_search=None if provider_key is None else (
                               lambda tar_bytes, host: provider_key_search(provider_key, tar_bytes,
                                                                           host)))
    if inference_opted(record):
        # a record counts only while its ssh process runs (a dropped session claims nothing)
        forward = forward_state(ctx.profile, idir)
        obs['inference_forward'] = {'path': forward['path'], 'recorded': forward['held'],
                                    'stale': forward['stale']}
    if record.get('provisioning'):
        mine = json.dumps(obs, sort_keys=True, default=str).encode('utf-8')
        obs['agent_server_secrets'] = {
            'host': agent_server_secret_scan(idir, session_key, secret_fp,
                                             {'this inspect (observations)': mine}),
            'p5_collection': obs['p5'].get('agent_server_secrets')}
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
    if guard is not None and guard.holds(json.dumps(out, sort_keys=True, default=str)):
        raise Refused('SECRET', 'the inspect record would hold the provider key: not written')
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


def index_rendering(entries):
    """The canonical rendering of a checkout's index (repo-inventory/2): one line per entry,
    ``<mode> <object id> <stage><TAB><path>`` (the mode in octal as git prints it, the path as
    raw UTF-8, never quoted), the lines sorted by their bytes, each ending in LF."""
    lines = sorted(f'{entry.mode:06o} {entry.oid} {entry.stage}\t{entry.path}'.encode('utf-8', 'surrogateescape')
                   for entry in entries)
    return b''.join(line + b'\n' for line in lines)


def repo_inventory(repo):
    """The checkout (repo-inventory/2): HEAD, the tracked changes and the index's digest, read
    in process by the shared repository-access module under the ``host`` configuration policy
    (decision 0014 row R8 and section 5; ``config_sources`` lists the files read). The index
    digest is the sha256 of ``index_rendering``; ``changed`` lists each tracked change as
    ``"XY path"`` (``git status --porcelain=v1 --untracked-files=no``, the path unquoted), sorted.
    A failure is recorded in ``error`` with the fields it left unknown as None, never raised."""
    ra = repository_access
    out = {'format': INVENTORY_FORMAT, 'path': posix(repo), 'head': None, 'changed': None,
           'index_sha256': None, 'index_count': None, 'config_policy': 'host', 'config_sources': None,
           'error': None}
    try:
        with ra.open_repository(repo, config='host') as opened:
            out['head'] = opened.head().commit
            entries = opened.index_entries()
            out['index_sha256'] = hashlib.sha256(index_rendering(entries)).hexdigest()
            out['index_count'] = len(entries)
            out['changed'] = sorted(f'{entry.xy} {entry.path}' for entry in opened.status(None, 'no'))
            out['config_sources'] = [posix(source) for source in opened.config_sources]
    except (ra.RepositoryError, ra.CannotRun) as exc:
        out['error'] = f'{exc.code}: {exc.message}'
    return out


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


def multipart_user_data(cloud_config, script, filename, boundary, what):
    """cloud-init multipart user-data: the ordinary cloud-config part, unchanged, then the
    test-only script part (cloud-init runs a text/x-shellscript part once, as root)."""
    mark = boundary.encode('ascii')
    for part_name, body in (('cloud-config', cloud_config), ('script', script)):
        if mark in body or b'\r' in body:
            raise Refused('REFUSED', f'{what} user-data: the {part_name} part holds the boundary '
                          'or a CR')
        try:
            body.decode('ascii')
        except UnicodeDecodeError as exc:
            raise Refused('REFUSED', f'{what} user-data: the {part_name} part is not ASCII') from exc

    def part(content_type, name, body):
        head = (f'--{boundary}\n'
                f'Content-Type: {content_type}; charset="us-ascii"\n'
                'MIME-Version: 1.0\n'
                'Content-Transfer-Encoding: 7bit\n'
                f'Content-Disposition: attachment; filename="{name}"\n\n')
        # the newline before the next delimiter belongs to the delimiter (RFC 2046)
        return head.encode('ascii') + body + b'\n'

    return (f'Content-Type: multipart/mixed; boundary="{boundary}"\n'
            'MIME-Version: 1.0\n\n').encode('ascii') + \
        part('text/cloud-config', 'cloud-config.yaml', cloud_config) + \
        part('text/x-shellscript', filename, script) + \
        f'--{boundary}--\n'.encode('ascii')


def netprobe_user_data(cloud_config, script):
    return multipart_user_data(cloud_config, script, 'aieh-netprobe.py', NETPROBE_BOUNDARY,
                               'netprobe')


def netprobe_seed(profile_path, instance_dir, name, public_key, script):
    """seed.iso for a validation instance: the generator's own steps (tools/nocloud_seed.py:
    pinned templates, the same substitutions), with user-data wrapped by netprobe_user_data.
    meta-data and network-config are the ordinary ones."""
    return wrapped_seed(profile_path, instance_dir, name, public_key, script, 'aieh-netprobe.py',
                        NETPROBE_BOUNDARY, 'netprobe')


def drill_seed(profile_path, instance_dir, name, public_key, script, provision_manifest):
    """seed.iso for a drill instance (E-01.2.2 slice (b)): the ordinary provisioned seed (the
    pinned templates, the same substitutions, the manifest) with the drill helper as a second
    user-data part."""
    return wrapped_seed(profile_path, instance_dir, name, public_key, script, 'aieh-drill.py',
                        DRILL_BOUNDARY, 'drill', provision_manifest)


def wrapped_seed(profile_path, instance_dir, name, public_key, script, filename, boundary, what,
                 provision_manifest=None):
    gen = load_seed_generator()
    try:
        profile, root = gen.load_profile(str(Path(profile_path).parent))
        name = gen.check_instance_name(profile, name)
        instance_id = gen.new_instance_id(name)
        templates = gen.read_templates(profile, root)
        values = {'agent_ssh_public_key': gen.read_public_key(str(public_key)),
                  'scratch_device': gen.scratch_device(profile),
                  'provision_manifest': gen.provision_manifest_value(provision_manifest),
                  'instance_id': instance_id, 'instance_name': name}
        rendered = gen.render(templates, values)
    except gen.Refused as exc:
        raise Refused('REFUSED', f'seed: {exc}') from exc
    ordinary = rendered['user-data']
    rendered['user-data'] = multipart_user_data(ordinary, script, filename, boundary, what)
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
            'provision_manifest_sha256': None if provision_manifest is None
            else hashlib.sha256(provision_manifest).hexdigest(),
            'validation': {'ordinary_user_data_sha256': hashlib.sha256(ordinary).hexdigest(),
                           'script_part_sha256': hashlib.sha256(script).hexdigest(),
                           'user_data': 'multipart/mixed: text/cloud-config (the ordinary '
                                        f'user-data), text/x-shellscript ({filename})'}}


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
    if validation.get('mode') == 'drill':
        if rules:
            raise Refused('REFUSED', f'drill record: guestfwd {rules}; a drill instance has none')
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
                            capture_output=True, text=True, check=False, timeout=120,
                            creationflags=_no_window().no_window_flags())
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
                                         stderr=err, cwd=str(self.dir), creationflags=_no_window().no_window_flags())
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
                            stdin=subprocess.DEVNULL, timeout=timeout, check=False,
                            creationflags=_no_window().no_window_flags())
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
    write_stamped_record(root / 'records', 'provision-fetch', result)
    return result


# ---------------------------------------------------------------- image-inspect (S-03.3)
#
# The Owner's decision (e) of 2026-11-10 (evidence/bootstrap-log.md, "Owner decisions on
# OA-05 and OA-12"): verify whether the exact pinned image contains the ACP adapters,
# without assuming the Dockerfile's defaults. Read only: the stage of the profile's lock is
# located and re-verified exactly as create --provision does, then the docker-archive's
# manifest, config and layers are read as data. Gzip layers are streamed (each re-hashed
# against the lock while read), applied in order as a union view (OCI/AUFS whiteouts and
# opaque directories honoured), and only the requested paths are reported. Nothing is
# extracted, nothing from the image is run, nothing is written.

IMAGE_INSPECT_MAX_PATHS = 64
IMAGE_INSPECT_MAX_HOPS = 40                 # symlinks followed per path (Linux MAXSYMLINKS)
IMAGE_INSPECT_MAX_CHILDREN = 200
IMAGE_INSPECT_MAX_JSON = 4 << 20            # a JSON file read for a field selector
IMAGE_INSPECT_MAX_VALUE = 4000              # characters of a reported field value
IMAGE_INSPECT_MAX_HISTORY = 400             # characters of a reported created_by line
IMAGE_INSPECT_STEP_CHARS = 160              # characters of each layer's created_by
IMAGE_INSPECT_KEYWORDS = re.compile(r'acp|claude|codex|node', re.IGNORECASE)
IMAGE_WHITEOUT = '.wh.'
IMAGE_OPAQUE = '.wh..wh..opq'
_TAR_KINDS = ((tarfile.REGTYPE, 'file'), (tarfile.AREGTYPE, 'file'), (tarfile.CONTTYPE, 'file'),
              (tarfile.DIRTYPE, 'dir'), (tarfile.SYMTYPE, 'symlink'), (tarfile.CHRTYPE, 'char'),
              (tarfile.BLKTYPE, 'block'), (tarfile.FIFOTYPE, 'fifo'),
              (tarfile.GNUTYPE_SPARSE, 'file'))
_TAR_KIND = dict(_TAR_KINDS)


class _ImageNode:
    """One path of the union view: what the last layer to write it recorded."""
    __slots__ = ('kind', 'mode', 'uid', 'gid', 'size', 'target', 'layer', 'src', 'hardlink')

    def __init__(self, kind, mode, uid, gid, size, target, layer, src, hardlink=None):
        self.kind, self.mode, self.uid, self.gid = kind, mode, uid, gid
        self.size, self.target, self.layer, self.src = size, target, layer, src
        self.hardlink = hardlink


class _HashingReader:
    """A layer member read once, front to back, hashed as it goes."""

    def __init__(self, raw):
        self.raw, self.digest, self.count = raw, hashlib.sha256(), 0

    def read(self, size=-1):
        data = self.raw.read(size)
        self.digest.update(data)
        self.count += len(data)
        return data

    def drain(self):
        for _ in iter(lambda: self.read(1 << 20), b''):
            pass


def image_member_path(name, where):
    """A layer member name as a '/'-free-rooted path ('' is the root); '..' refuses."""
    parts = [p for p in name.replace('\\', '/').split('/') if p not in ('', '.')]
    if '..' in parts:
        raise Refused('IMAGE_FORMAT', f'{where}: member {name!r} leaves the image root')
    return '/'.join(parts)


def parse_image_path_spec(spec):
    """'PATH' or 'PATH#key#key...': an absolute image path and an optional JSON field."""
    if not isinstance(spec, str) or '\0' in spec or len(spec) > 4096:
        raise Refused('REFUSED', f'--path {spec!r} is not a usable path')
    path, *selector = spec.split('#')
    if not path.startswith('/') or any(not k for k in selector):
        raise Refused('REFUSED', f'--path {spec!r}: needs an absolute path and non-empty '
                      'field keys (PATH or PATH#key#key)')
    return {'spec': spec, 'path': path, 'selector': selector}


class ImageView:
    """The union filesystem of a docker-archive's layers, metadata only."""

    def __init__(self):
        self.nodes = {'': _ImageNode('dir', 0o755, 0, 0, 0, None, None, None)}
        self.children = {'': set()}
        self.anomalies = []
        self.anomaly_count = 0

    def _anomaly(self, text):
        self.anomaly_count += 1
        if len(self.anomalies) < 20:
            self.anomalies.append(text)

    def _remove(self, path):
        node = self.nodes.pop(path, None)
        if node is None:
            return
        if node.kind == 'dir':
            for child in list(self.children.pop(path, ())):
                self._remove(f'{path}/{child}' if path else child)
        parent, _, base = path.rpartition('/')
        self.children.get(parent, set()).discard(base)

    def _ensure_parents(self, path, layer):
        parent = ''
        for part in path.split('/')[:-1]:
            here = f'{parent}/{part}' if parent else part
            node = self.nodes.get(here)
            if node is not None and node.kind != 'dir':
                # BuildKit diffs never write through a lower non-directory; the overlay2
                # graph driver would shadow it with a directory, which is what is applied
                self._anomaly(f'layer {layer}: {here} is a {node.kind} below {path}')
                self._remove(here)
                node = None
            if node is None:
                self.nodes[here] = _ImageNode('dir', 0o755, 0, 0, 0, None, layer, None)
                self.children[here] = set()
                self.children[parent].add(part)
            parent = here

    def _put(self, path, node):
        self._ensure_parents(path, node.layer)
        old = self.nodes.get(path)
        if old is not None and not (old.kind == 'dir' and node.kind == 'dir'):
            self._remove(path)
        self.nodes[path] = node
        if node.kind == 'dir':
            self.children.setdefault(path, set())
        parent, _, base = path.rpartition('/')
        self.children[parent].add(base)

    def apply_layer(self, layer, entries):
        """entries: [(ordinal, path, TarInfo-like)] of one layer, in archive order.
        Whiteouts and opaque markers act on the lower layers only, so they are applied
        first; then the entries in order (a hard link sees earlier entries of its layer)."""
        for _ordinal, path, _info in entries:
            parent, _, base = path.rpartition('/')
            if base == IMAGE_OPAQUE:
                node = self.nodes.get(parent)
                if node is not None and node.kind == 'dir':
                    for child in list(self.children.get(parent, ())):
                        self._remove(f'{parent}/{child}' if parent else child)
            elif base.startswith(IMAGE_WHITEOUT) and not base.startswith(IMAGE_WHITEOUT * 2):
                self._remove(f'{parent}/{base[len(IMAGE_WHITEOUT):]}' if parent
                             else base[len(IMAGE_WHITEOUT):])
        for ordinal, path, info in entries:
            base = path.rpartition('/')[2]
            if not path or base.startswith(IMAGE_WHITEOUT):
                continue                      # the root itself, whiteouts and AUFS metadata
            if info.type == tarfile.LNKTYPE:
                target = image_member_path(info.linkname, f'layer {layer}')
                linked = self.nodes.get(target)
                if linked is None or linked.kind == 'dir':
                    self._anomaly(f'layer {layer}: hard link {path} -> {target} has no target')
                    continue
                self._put(path, _ImageNode(linked.kind, linked.mode, linked.uid, linked.gid,
                                           linked.size, linked.target, layer, linked.src,
                                           hardlink='/' + target))
                continue
            kind = _TAR_KIND.get(info.type)
            if kind is None:
                self._anomaly(f'layer {layer}: {path} has tar type {info.type!r}; skipped')
                continue
            self._put(path, _ImageNode(kind, info.mode & 0o7777, info.uid, info.gid,
                                       info.size if kind == 'file' else 0,
                                       info.linkname if kind == 'symlink' else None,
                                       layer, (layer, ordinal) if kind == 'file' else None))

    def resolve(self, path, follow_last=True):
        """Resolve inside the image root: (resolved path or None, node or None, hops, error).
        A symlink chain is followed for at most IMAGE_INSPECT_MAX_HOPS hops; '..' above
        the root and an over-long chain are refused, never clamped or followed outside."""
        stack = [p for p in reversed(path.split('/'))]
        cur, hops = '', []
        while stack:
            comp = stack.pop()
            if comp in ('', '.'):
                continue
            if comp == '..':
                if not cur:
                    return None, None, hops, 'escapes the image root'
                cur = cur.rpartition('/')[0]
                continue
            here = f'{cur}/{comp}' if cur else comp
            node = self.nodes.get(here)
            if node is None:
                return None, None, hops, None
            last = not any(p not in ('', '.') for p in stack)
            if node.kind == 'symlink' and (follow_last or not last):
                if len(hops) >= IMAGE_INSPECT_MAX_HOPS:
                    return None, None, hops, f'more than {IMAGE_INSPECT_MAX_HOPS} symlink hops'
                hops.append({'path': '/' + here, 'target': node.target})
                if node.target.startswith('/'):
                    cur = ''
                stack.extend(reversed(node.target.split('/')))
                continue
            if not last and node.kind != 'dir':
                return None, None, hops, None
            cur = here
        return cur, self.nodes[cur], hops, None


def _node_fields(node):
    out = {'type': node.kind, 'mode': f'{node.mode:04o}', 'uid': node.uid, 'gid': node.gid,
           'size': node.size, 'layer': node.layer}
    if node.hardlink:
        out['hardlink_to'] = node.hardlink
    return out


def _json_field(data, selector):
    try:
        value = json.loads(data.decode('utf-8'))
    except (UnicodeDecodeError, ValueError) as exc:
        return {'field_error': f'not JSON ({exc.__class__.__name__})'}
    for key in selector:
        if isinstance(value, dict) and key in value:
            value = value[key]
        elif isinstance(value, list) and key.isdigit() and int(key) < len(value):
            value = value[int(key)]
        else:
            return {'field_error': f'no field {"#".join(selector)}'}
    text = json.dumps(value, sort_keys=True)
    if len(text) > IMAGE_INSPECT_MAX_VALUE:
        return {'field': '#'.join(selector), 'value_truncated': text[:IMAGE_INSPECT_MAX_VALUE]}
    return {'field': '#'.join(selector), 'value': value}


def _layer_stream(tf, member, locked, index, consume):
    """Stream one layer member as a tar (gzip or plain), call consume(ordinal, TarInfo,
    tarfile) per entry, and check the member's bytes against its locked digest and size."""
    reader = _HashingReader(tf.extractfile(member))
    try:
        with tarfile.open(fileobj=reader, mode='r|*') as layer_tf:
            for ordinal, info in enumerate(layer_tf):
                consume(ordinal, info, layer_tf)
                layer_tf.members = []         # stream mode would keep every TarInfo
    except (tarfile.TarError, EOFError, zlib.error) as exc:
        raise Refused('IMAGE_FORMAT', f'layer {index}: not a gzip or plain tar stream ({exc})') \
            from exc
    reader.drain()
    got = ('sha256:' + reader.digest.hexdigest(), reader.count)
    if got != (locked['digest'], locked['size']):
        raise Refused('IMAGE_MISMATCH', f'layer {index}: read {got[0]} ({got[1]} bytes); the '
                      f'lock says {locked["digest"]} ({locked["size"]} bytes)')


def read_image_archive(handle, image, specs, text=None):
    """Report the requested paths of a docker-archive (an open binary file) whose config and
    layers must match the locked image; see the section comment. text: the requests of
    parse_image_text_requests, answered under 'text' (see the text mode's section comment)."""
    with tarfile.open(fileobj=handle, mode='r:') as tf:
        by_name = {m.name: m for m in tf.getmembers()}
        try:
            entries = json.loads(tf.extractfile(by_name['manifest.json']).read())
            config_name, layer_names = entries[0]['Config'], entries[0]['Layers']
            if len(entries) != 1 or not isinstance(layer_names, list):
                raise ValueError('manifest.json is not one image with a layer list')
            members = [by_name[n] for n in layer_names]
            config_bytes = tf.extractfile(by_name[config_name]).read()
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise Refused('IMAGE_FORMAT', f'not a single-image docker-archive ({exc!r})') from exc
        config_digest = 'sha256:' + hashlib.sha256(config_bytes).hexdigest()
        if config_digest != image['config_digest']:
            raise Refused('IMAGE_MISMATCH', f'config is {config_digest}; the lock says '
                          f'{image["config_digest"]}')
        if len(members) != len(image['layers']):
            raise Refused('IMAGE_MISMATCH', f'{len(members)} layers; the lock has '
                          f'{len(image["layers"])}')
        config = json.loads(config_bytes)
        view = ImageView()
        for index, member in enumerate(members):
            batch = []
            _layer_stream(tf, member, image['layers'][index], index,
                          lambda o, info, _tf: batch.append(
                              (o, image_member_path(info.name, f'layer {index}'), info)))
            view.apply_layer(index, batch)
        reports, wanted = [], {}
        for spec in specs:
            reports.append(_image_path_report(view, spec, wanted))
        jobs, done = {}, set()
        text_out = _image_text_plan(view, text, jobs) if text is not None else None
        contents = {}
        for index in sorted({src[0] for src in wanted} | {src[0] for src in jobs}):
            def keep(ordinal, info, layer_tf, index=index):
                key = (index, ordinal)
                if key not in wanted and key not in jobs:
                    return
                handle_ = layer_tf.extractfile(info)
                digest, kept = hashlib.sha256(), []
                held = [] if key in jobs and info.size <= IMAGE_TEXT_MAX_FILE else None
                for block in iter(lambda: handle_.read(1 << 20), b''):
                    digest.update(block)
                    if wanted.get(key) and sum(map(len, kept)) <= IMAGE_INSPECT_MAX_JSON:
                        kept.append(block)
                    if held is not None:
                        held.append(block)
                if key in wanted:
                    contents[key] = (digest.hexdigest(), b''.join(kept))
                if key in jobs:
                    data = b''.join(held) if held is not None else None
                    held, cache = None, {}
                    for job in jobs[key]:
                        job(data, digest.hexdigest(), info.size, cache)
                    done.add(key)
            _layer_stream(tf, members[index], image['layers'][index], index, keep)
        missed = sorted(set(jobs) - done)
        if missed:
            raise Refused('IMAGE_FORMAT', f'layer {missed[0][0]} entry {missed[0][1]} was not '
                          'met again')
    for report in reports:
        src = report.pop('_src', None)
        if src is None:
            continue
        if src not in contents:
            raise Refused('IMAGE_FORMAT', f'layer {src[0]} entry {src[1]} was not met again')
        sha, data = contents[src]
        report['sha256'] = sha
        if report.get('_selector'):
            selector = report.pop('_selector')
            report.update(_json_field(data, selector) if len(data) <= IMAGE_INSPECT_MAX_JSON
                          else {'field_error': 'larger than the JSON read bound'})
    out = {'config': image_config_summary(config, len(members)), 'paths': reports,
           'anomalies': {'count': view.anomaly_count, 'examples': view.anomalies},
           'nodes': len(view.nodes)}
    if text_out is not None:
        out['text'] = dict(_image_text_finish(text_out), bounds=_image_text_bounds(text))
    return out


def _image_text_bounds(text):
    return {'context_bytes': text['context'], 'max_matches_per_file': text['max_matches'],
            'max_matches_per_request': IMAGE_TEXT_MAX_REQUEST_MATCHES,
            'max_count_per_file': IMAGE_TEXT_MAX_COUNT, 'max_files': IMAGE_TEXT_MAX_FILES,
            'max_list': IMAGE_TEXT_MAX_LIST, 'max_file_bytes': IMAGE_TEXT_MAX_FILE,
            'max_excerpt_file_bytes': IMAGE_TEXT_MAX_EXCERPT_FILE,
            'max_module_bytes': IMAGE_TEXT_MAX_MODULE, 'max_line_chars': IMAGE_TEXT_MAX_LINE,
            'max_match_bytes': IMAGE_TEXT_MAX_MATCH, 'max_distinct': IMAGE_TEXT_MAX_DISTINCT,
            'max_strings_per_module': IMAGE_TEXT_MAX_STRINGS,
            'max_string_chars': IMAGE_TEXT_MAX_TOKEN}


def _image_path_report(view, spec, wanted):
    report = {'path': spec['path']}
    if spec['selector']:
        report['selector'] = '#'.join(spec['selector'])
    _, entry, hops, error = view.resolve(spec['path'], follow_last=False)
    if error:
        return dict(report, present=False, refused=error, links=hops)
    if entry is None:
        return dict(report, present=False, links=hops) if hops else dict(report, present=False)
    report.update(present=True, **_node_fields(entry))
    if entry.kind == 'symlink':
        report['link_target'] = entry.target
    final_path, final, hops, error = view.resolve(spec['path'], follow_last=True)
    if hops:
        report['links'] = hops
    if error:
        report['refused'] = error
        return report
    if final is None:
        report['dangling'] = True
        return report
    if hops:
        report['real_path'] = '/' + final_path
    if final is not entry:
        report['resolved'] = dict(path='/' + final_path, **_node_fields(final))
    if final.kind == 'dir':
        names = sorted(view.children.get(final_path, ()))
        report['children_total'] = len(names)
        report['children'] = names[:IMAGE_INSPECT_MAX_CHILDREN]
    elif final.kind == 'file':
        report['_src'] = final.src
        wanted[final.src] = wanted.get(final.src, False) or bool(spec['selector'])
        if spec['selector']:
            report['_selector'] = spec['selector']
    if spec['selector'] and final.kind != 'file':
        report['field_error'] = f'resolves to a {final.kind}, not a file'
    return report


def image_config_summary(config, layer_count):
    """The config's runtime fields, the Env entries that name PATH or a keyword, and the
    history lines whose created_by names a keyword, each with the layer it made."""
    inner = config.get('config') or {}
    env = [e for e in inner.get('Env') or [] if isinstance(e, str) and
           (e.startswith('PATH=') or IMAGE_INSPECT_KEYWORDS.search(e.split('=', 1)[0]))]
    history, layer, lines, steps = config.get('history') or [], 0, [], []
    for position, step in enumerate(history):
        created = str(step.get('created_by', ''))
        empty = bool(step.get('empty_layer'))
        if not empty:
            steps.append(created[:IMAGE_INSPECT_STEP_CHARS])
        if IMAGE_INSPECT_KEYWORDS.search(created):
            lines.append({'history': position, 'layer': None if empty else layer,
                          'created_by': created[:IMAGE_INSPECT_MAX_HISTORY],
                          'truncated': len(created) > IMAGE_INSPECT_MAX_HISTORY})
        layer += 0 if empty else 1
    return {'user': inner.get('User'), 'entrypoint': inner.get('Entrypoint'),
            'cmd': inner.get('Cmd'), 'working_dir': inner.get('WorkingDir'), 'env': env,
            'history_total': len(history), 'history_layers': layer,
            'history_layers_match': layer == layer_count, 'history_matches': lines,
            'layer_steps': steps if layer == layer_count else None}


# ---------------------------------------------------------------- image-inspect text mode (S-03.3 D-1)
#
# The Owner's decision of 2026-11-11 on S-03.3 D-1 (option A): one more read-only inspection of
# the staged, verified archive, reading the bundled ACP adapter, its SDK and CLI, and the agent
# server's own code, as data. The text requests read file content from the same union view, in
# the same second pass that hashes the --path files, and report bounded data only: a listing by
# glob, a line excerpt of a text file, the matches of a pattern with a bounded context, the
# distinct values a pattern matches and, inside a PyInstaller executable, its PYZ modules' names,
# matches and string constants (the zlib data is inflated under a bound and its marshal data
# walked as data, never loaded as code). Nothing from the image is written, extracted or run;
# every count is capped and a reached cap is reported, never passed silently.

IMAGE_TEXT_MAX_REQUESTS = 96                # --list, --excerpt, --search, --distinct, --strings
IMAGE_TEXT_MAX_LIST = 400                   # entries reported per --list
IMAGE_TEXT_MAX_FILES = 400                  # files (or PYZ modules) read per request
IMAGE_TEXT_MAX_SKIPPED = 50                 # non-file glob matches reported per request
IMAGE_TEXT_MAX_FILE = 512 << 20             # bytes of one file held for text
IMAGE_TEXT_MAX_EXCERPT_FILE = 64 << 20      # bytes of a file an excerpt decodes
IMAGE_TEXT_MAX_MODULE = 16 << 20            # inflated bytes of one PYZ module
IMAGE_TEXT_MAX_EXCERPT_LINES = 200
IMAGE_TEXT_MAX_LINE = 600                   # characters of a reported line
IMAGE_TEXT_DEFAULT_CONTEXT = 160            # bytes before and after a match
IMAGE_TEXT_MAX_CONTEXT = 400
IMAGE_TEXT_DEFAULT_MATCHES = 8              # matches reported per file and request
IMAGE_TEXT_MAX_MATCHES = 50
IMAGE_TEXT_MAX_REQUEST_MATCHES = 200        # matches reported per request over all its files
IMAGE_TEXT_MAX_COUNT = 100000               # matches counted per file and request
IMAGE_TEXT_MAX_MATCH = 200                  # bytes of a reported match or distinct value
IMAGE_TEXT_MAX_DISTINCT = 400               # distinct values reported per request
IMAGE_TEXT_MAX_DISTINCT_HELD = 20000        # distinct values held per file
IMAGE_TEXT_MAX_PATTERN = 256
IMAGE_TEXT_MAX_STRINGS_MODULES = 8          # PYZ modules per --strings
IMAGE_TEXT_MAX_STRINGS = 4000               # string constants and names reported per module
IMAGE_TEXT_MAX_TOKEN = 240                  # characters of a reported string
IMAGE_TEXT_MARSHAL_OBJECTS = 2000000
IMAGE_TEXT_MARSHAL_DEPTH = 200
IMAGE_TEXT_OPS = ('list', 'excerpt', 'search', 'distinct', 'strings')
PYI_COOKIE = b'MEI' + bytes([12, 11, 10, 11, 14])      # PyInstaller's CArchive cookie magic
PYI_COOKIE_FORMAT = '!8sIIII64s'
PYI_TOC_ENTRY = '!IIIIBc'
PYI_PYZ_MAGIC = b'PYZ' + bytes([0])
PYI_PYZ_KINDS = {0: 'module', 1: 'package', 2: 'data', 3: 'namespace package'}
PYI_CODE_VERSIONS = (311, 312, 313)                    # the code-object layout the walker knows
_IMAGE_NL = bytes([10])
_IMAGE_NUL = bytes([0])
_IMAGE_CONTROL = re.compile('[' + chr(0) + '-' + chr(8) + chr(11) + chr(12) + chr(14) + '-' +
                            chr(31) + chr(127) + '-' + chr(159) + ']')
_IMAGE_GLOB_CHARS = ('*', '?', '[')


def _image_render(data):
    """Bytes from the image as reportable text: UTF-8 where valid, every other byte and every
    control character but tab, newline and carriage return as a backslash-x escape."""
    text = bytes(data).decode('utf-8', 'backslashreplace')
    return _IMAGE_CONTROL.sub(lambda m: '%sx%02x' % (chr(92), ord(m.group())), text)


def _image_glob_component(part, spec):
    out, i = [], 0
    while i < len(part):
        c = part[i]
        if c == '*':
            out.append('[^/]*')
        elif c == '?':
            out.append('[^/]')
        elif c == '[':
            j = part.find(']', i + 2)
            if j < 0:
                raise Refused('REFUSED', f'glob {spec!r}: an unclosed [')
            body = part[i + 1:j]
            negate = body[:1] == '!'
            body = ''.join(re.escape(ch) if ch != '-' else '-' for ch in body[1 if negate else 0:])
            out.append(('[^/' if negate else '[') + body + ']')
            i = j
        else:
            out.append(re.escape(c))
        i += 1
    return ''.join(out)


def image_glob_regex(spec):
    """An absolute image glob ('*', '?', '[...]' within one component, '**' for any number of
    components) as a compiled regex over the union view's root-relative paths."""
    if not isinstance(spec, str) or not spec.startswith('/') or '\0' in spec or len(spec) > 1024:
        raise Refused('REFUSED', f'glob {spec!r}: needs an absolute image path or glob')
    parts = spec.split('/')[1:]
    if any(p in ('', '.', '..') for p in parts):
        raise Refused('REFUSED', f'glob {spec!r}: empty, . or .. components are refused')
    rx = []
    for index, part in enumerate(parts):
        last = index == len(parts) - 1
        if part == '**':
            rx.append('[^/]+(?:/[^/]+)*' if last else '(?:[^/]+/)*')
        else:
            rx.append(_image_glob_component(part, spec) + ('' if last else '/'))
    return re.compile(''.join(rx), re.DOTALL)


def _image_text_target(spec, what, member=None):
    """A request's target: a path glob, or EXE!MODULEGLOB (the PYZ modules of a PyInstaller
    executable at the exact image path EXE). member: True requires the second form."""
    if not isinstance(spec, str):
        raise Refused('REFUSED', f'{what}: needs a value')
    if '!' in spec:
        exe, _, modules = spec.partition('!')
        if member is False:
            raise Refused('REFUSED', f'{what} {spec!r}: takes a path, not EXE!MODULE')
        if not exe.startswith('/') or '\0' in exe or len(exe) > 1024 or \
                any(c in exe for c in _IMAGE_GLOB_CHARS):
            raise Refused('REFUSED', f'{what} {spec!r}: EXE must be an exact absolute path')
        if not modules or len(modules) > 256 or '/' in modules or '\0' in modules or \
                '!' in modules:
            raise Refused('REFUSED', f'{what} {spec!r}: needs a module name or glob after !')
        return {'exe': exe, 'modules': modules}
    if member:
        raise Refused('REFUSED', f'{what} {spec!r}: needs EXE!MODULE (a PyInstaller executable)')
    return {'_rx_path': image_glob_regex(spec)}


def _image_text_pattern(pattern, what):
    if not isinstance(pattern, str) or not pattern or len(pattern) > IMAGE_TEXT_MAX_PATTERN or \
            '\0' in pattern:
        raise Refused('REFUSED', f'{what}: a pattern of 1 to {IMAGE_TEXT_MAX_PATTERN} characters')
    try:
        rx = re.compile(pattern.encode('utf-8'))
    except re.error as exc:
        raise Refused('REFUSED', f'{what} {pattern!r}: not a regular expression ({exc})') from exc
    if rx.search(b'') is not None:
        raise Refused('REFUSED', f'{what} {pattern!r}: matches the empty string')
    if rx.groups > 1:
        raise Refused('REFUSED', f'{what} {pattern!r}: at most one group')
    return rx


def parse_image_text_requests(lists=None, excerpts=None, searches=None, distincts=None,
                              strings=None, context=None, max_matches=None):
    """The text requests of one image-inspect run, validated before anything is read."""
    context = IMAGE_TEXT_DEFAULT_CONTEXT if context is None else context
    max_matches = IMAGE_TEXT_DEFAULT_MATCHES if max_matches is None else max_matches
    if isinstance(context, bool) or not isinstance(context, int) or \
            not 0 <= context <= IMAGE_TEXT_MAX_CONTEXT:
        raise Refused('REFUSED', f'--context: 0 to {IMAGE_TEXT_MAX_CONTEXT} bytes')
    if isinstance(max_matches, bool) or not isinstance(max_matches, int) or \
            not 1 <= max_matches <= IMAGE_TEXT_MAX_MATCHES:
        raise Refused('REFUSED', f'--max-matches: 1 to {IMAGE_TEXT_MAX_MATCHES}')
    requests = []
    for spec in lists or ():
        requests.append(dict(op='list', glob=spec, **_image_text_target(spec, '--list')))
    for path, start, end in excerpts or ():
        _image_text_target(path, '--excerpt', member=False)
        if not path.startswith('/') or any(c in path for c in _IMAGE_GLOB_CHARS):
            raise Refused('REFUSED', f'--excerpt {path!r}: an exact absolute path')
        if isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int) or \
                not isinstance(end, int) or not 1 <= start <= end or \
                end - start + 1 > IMAGE_TEXT_MAX_EXCERPT_LINES:
            raise Refused('REFUSED', f'--excerpt {path!r} {start} {end}: lines START to END, '
                          f'1 <= START <= END, at most {IMAGE_TEXT_MAX_EXCERPT_LINES} lines')
        requests.append({'op': 'excerpt', 'path': path, 'start': start, 'end': end})
    for op, pairs in (('search', searches), ('distinct', distincts)):
        for spec, pattern in pairs or ():
            requests.append(dict(op=op, glob=spec, pattern=pattern,
                                 _rx=_image_text_pattern(pattern, f'--{op}'),
                                 **_image_text_target(spec, f'--{op}')))
    for spec in strings or ():
        requests.append(dict(op='strings', glob=spec,
                             **_image_text_target(spec, '--strings', member=True)))
    if len(requests) > IMAGE_TEXT_MAX_REQUESTS:
        raise Refused('REFUSED', f'at most {IMAGE_TEXT_MAX_REQUESTS} text requests')
    return {'requests': requests, 'context': context, 'max_matches': max_matches}


def _image_matches(data, rx, context, max_matches, lines):
    """The first max_matches matches of rx in data with their context; all matches counted
    up to IMAGE_TEXT_MAX_COUNT. Line numbers only for a text file."""
    found, total, line, last = [], 0, 1, 0
    for m in rx.finditer(data):
        total += 1
        if len(found) < max_matches:
            s, e = m.span()
            item = {'offset': s}
            if lines:
                line += data.count(_IMAGE_NL, last, s)
                last = s
                item['line'] = line
            item['match'] = _image_render(data[s:min(e, s + IMAGE_TEXT_MAX_MATCH)])
            if e - s > IMAGE_TEXT_MAX_MATCH:
                item['match_truncated'] = True
            item['before'] = _image_render(data[max(0, s - context):s])
            item['after'] = _image_render(data[e:e + context])
            found.append(item)
        if total >= IMAGE_TEXT_MAX_COUNT:
            return found, total, True
    return found, total, False


def _image_distinct(data, rx):
    counts, total, full = {}, 0, False
    for m in rx.finditer(data):
        total += 1
        key = (m.group(1) if rx.groups else m.group()) or b''
        key = key[:IMAGE_TEXT_MAX_MATCH]
        if key in counts:
            counts[key] += 1
        elif len(counts) < IMAGE_TEXT_MAX_DISTINCT_HELD:
            counts[key] = 1
        else:
            full = True
        if total >= IMAGE_TEXT_MAX_COUNT:
            return counts, total, True, full
    return counts, total, False, full


def _image_excerpt(data, start, end):
    if len(data) > IMAGE_TEXT_MAX_EXCERPT_FILE:
        return {'refused': 'larger than the excerpt bound'}
    if _IMAGE_NUL in data:
        return {'refused': 'binary (a NUL byte)'}
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        return {'refused': 'binary (not UTF-8)'}
    lines = text.split(chr(10))
    if lines and lines[-1] == '':
        lines.pop()
    out = []
    for n in range(start, min(end, len(lines)) + 1):
        raw = lines[n - 1].rstrip(chr(13))
        item = {'n': n, 'text': _IMAGE_CONTROL.sub(
            lambda m: '%sx%02x' % (chr(92), ord(m.group())), raw[:IMAGE_TEXT_MAX_LINE])}
        if len(raw) > IMAGE_TEXT_MAX_LINE:
            item.update(truncated=True, chars=len(raw))
        out.append(item)
    return {'lines_total': len(lines), 'lines': out}


class _PyiError(ValueError):
    """A PyInstaller archive or marshal structure this reader does not accept."""


def _marshal_toc(buf, pos):
    """PyInstaller's PYZ table of contents: marshal data of lists, tuples, a dict, strings and
    ints only; anything else is refused (the stdlib marshal is not safe for untrusted data)."""
    refs = []

    def take(n):
        nonlocal pos
        if n < 0 or pos + n > len(buf):
            raise _PyiError('PYZ table of contents: truncated')
        chunk = buf[pos:pos + n]
        pos += n
        return bytes(chunk)

    def u32():
        return struct.unpack('<I', take(4))[0]

    def obj(depth):
        if depth > 8:
            raise _PyiError('PYZ table of contents: nested too deep')
        code = take(1)[0]
        kind = chr(code & 0x7f)
        slot = None
        if code & 0x80:
            slot = len(refs)
            refs.append(None)
        if kind in '([':
            n = u32()
            if n > 1000000:
                raise _PyiError('PYZ table of contents: too many entries')
            value = [obj(depth + 1) for _ in range(n)]
            value = tuple(value) if kind == '(' else value
        elif kind == ')':
            value = tuple(obj(depth + 1) for _ in range(take(1)[0]))
        elif kind == '{':
            value = {}
            while buf[pos:pos + 1] != b'0':
                key = obj(depth + 1)
                value[key] = obj(depth + 1)
            take(1)
        elif kind == 'i':
            value = struct.unpack('<i', take(4))[0]
        elif kind in 'zZ':
            value = take(take(1)[0]).decode('ascii')
        elif kind in 'aA':
            value = take(u32()).decode('ascii')
        elif kind in 'tu':
            value = take(u32()).decode('utf-8', 'surrogatepass')
        elif kind == 'r':
            index = u32()
            if index >= len(refs) or refs[index] is None:
                raise _PyiError('PYZ table of contents: a bad back reference')
            value = refs[index]
        else:
            raise _PyiError(f'PYZ table of contents: marshal type {kind!r} is not accepted')
        if slot is not None:
            refs[slot] = value
        return value

    try:
        toc = obj(0)
    except UnicodeDecodeError as exc:
        raise _PyiError('PYZ table of contents: a name is not text') from exc
    items = toc.items() if isinstance(toc, dict) else toc
    modules = {}
    for item in items if isinstance(items, (list, tuple, type({}.items()))) else ():
        name, entry = item if isinstance(item, (tuple, list)) and len(item) == 2 else (None, None)
        if not isinstance(name, str) or not isinstance(entry, (tuple, list)) or len(entry) != 3 or \
                not all(isinstance(v, int) and not isinstance(v, bool) for v in entry):
            raise _PyiError('PYZ table of contents: an entry is not (name, (type, offset, length))')
        modules[name] = tuple(entry)
    if not modules:
        raise _PyiError('PYZ table of contents: no entries')
    return modules


def _pyi_archive_at(data, pos):
    size = struct.calcsize(PYI_COOKIE_FORMAT)
    if pos + size > len(data):
        raise _PyiError('the cookie is truncated')
    _, length, toc_offset, toc_length, pyver, _ = struct.unpack_from(PYI_COOKIE_FORMAT, data, pos)
    start = pos + size - length
    if start < 0 or toc_offset + toc_length > length:
        raise _PyiError('the cookie does not describe the archive around it')
    entries, at, end = [], start + toc_offset, start + toc_offset + toc_length
    head = struct.calcsize(PYI_TOC_ENTRY)
    while at < end:
        entry_len, offset, dlen, ulen, flag, kind = struct.unpack_from(PYI_TOC_ENTRY, data, at)
        if entry_len < head or at + entry_len > end or offset + dlen > length:
            raise _PyiError('a table of contents entry is out of bounds')
        name = bytes(data[at + head:at + entry_len]).rstrip(_IMAGE_NUL).decode('utf-8', 'replace')
        entries.append((name, offset, dlen, ulen, flag, kind))
        at += entry_len
    pyz = [e for e in entries if e[5] == b'z']
    if not pyz:
        raise _PyiError('no PYZ entry in the archive')
    name, offset, dlen, _, flag, _ = pyz[0]
    blob = memoryview(data)[start + offset:start + offset + dlen]
    if flag or bytes(blob[:4]) != PYI_PYZ_MAGIC or len(blob) < 12:
        raise _PyiError(f'PYZ entry {name!r} is not an uncompressed PYZ archive')
    toc_at = struct.unpack('!i', bytes(blob[8:12]))[0]
    if not 12 <= toc_at < len(blob):
        raise _PyiError(f'PYZ entry {name!r}: its table of contents is out of bounds')
    return {'cookie_offset': pos, 'python': pyver, 'entries': len(entries), 'pyz_entry': name,
            'pyz_count': len(pyz), 'pyz_magic': bytes(blob[4:8]).hex(),
            'modules': _marshal_toc(blob, toc_at), '_pyz': blob}


def pyi_archive(data):
    """The PYZ archive of a PyInstaller executable (its bytes): the last cookie that describes
    a consistent archive (the bootloader's own copy of the magic is skipped)."""
    pos, last = data.rfind(PYI_COOKIE), 'no PyInstaller cookie'
    for _ in range(4):
        if pos < 0:
            break
        try:
            return _pyi_archive_at(data, pos)
        except (_PyiError, struct.error) as exc:
            last = str(exc)
        pos = data.rfind(PYI_COOKIE, 0, pos)
    raise _PyiError(last)


def pyz_module(archive, name):
    """One PYZ entry inflated under IMAGE_TEXT_MAX_MODULE: bytes, or the reason as a str."""
    kind, offset, length = archive['modules'][name]
    pyz = archive['_pyz']
    if offset < 0 or length < 0 or offset + length > len(pyz):
        return 'its data is out of bounds'
    inflater = zlib.decompressobj()
    try:
        out = inflater.decompress(pyz[offset:offset + length], IMAGE_TEXT_MAX_MODULE + 1)
    except zlib.error as exc:
        return f'not zlib data ({exc})'
    if len(out) > IMAGE_TEXT_MAX_MODULE or inflater.unconsumed_tail:
        return 'larger than the module bound'
    return out


class _MarshalCode:
    __slots__ = ('qualname', 'line', 'filename', 'consts', 'names')


class _MarshalWalk:
    """A walk of one module's marshal data (CPython 3.11 to 3.13 code objects) that keeps the
    string constants and names of each code object; nothing is turned into code."""
    NULL = object()

    def __init__(self, buf):
        self.buf, self.pos, self.refs, self.count = buf, 0, [], 0

    def take(self, n):
        if n < 0 or self.pos + n > len(self.buf):
            raise _PyiError(f'marshal data truncated at {self.pos}')
        chunk = self.buf[self.pos:self.pos + n]
        self.pos += n
        return bytes(chunk)

    def i32(self):
        return struct.unpack('<i', self.take(4))[0]

    def obj(self, depth=0):
        if depth > IMAGE_TEXT_MARSHAL_DEPTH:
            raise _PyiError('marshal data nested too deep')
        self.count += 1
        if self.count > IMAGE_TEXT_MARSHAL_OBJECTS:
            raise _PyiError('marshal data has too many objects')
        at = self.pos
        code = self.take(1)[0]
        kind = chr(code & 0x7f)
        slot = None
        if code & 0x80:
            slot = len(self.refs)
            self.refs.append(None)
        value = self.value(kind, depth, at)
        if slot is not None:
            self.refs[slot] = value
        return value

    def value(self, kind, depth, at):
        simple = {'0': self.NULL, 'N': None, 'T': True, 'F': False, 'S': 'StopIteration',
                  '.': Ellipsis}
        if kind in simple:
            return simple[kind]
        if kind == 'i':
            return self.i32()
        if kind == 'l':
            n = self.i32()
            digits = struct.unpack(f'<{abs(n)}H', self.take(2 * abs(n))) if n else ()
            value = sum(d << (15 * i) for i, d in enumerate(digits))
            return -value if n < 0 else value
        if kind == 'g':
            return struct.unpack('<d', self.take(8))[0]
        if kind == 'y':
            return complex(*struct.unpack('<dd', self.take(16)))
        if kind in 'fx':
            parts = [float(self.take(self.take(1)[0]).decode('ascii'))
                     for _ in range(1 if kind == 'f' else 2)]
            return parts[0] if kind == 'f' else complex(*parts)
        if kind == 's':
            return bytes(self.take(self.i32()))
        if kind in 'zZ':
            return self.take(self.take(1)[0]).decode('ascii', 'replace')
        if kind in 'aAtu':
            return self.take(self.i32()).decode('utf-8', 'surrogatepass')
        if kind in '([<>':
            n = self.i32()
            if n < 0 or n > len(self.buf):
                raise _PyiError(f'marshal sequence length {n} at {at}')
            return tuple(self.obj(depth + 1) for _ in range(n))
        if kind == ')':
            return tuple(self.obj(depth + 1) for _ in range(self.take(1)[0]))
        if kind == '{':
            pairs = []
            while True:
                key = self.obj(depth + 1)
                if key is self.NULL:
                    return tuple(pairs)
                pairs.append((key, self.obj(depth + 1)))
        if kind == 'r':
            index = struct.unpack('<I', self.take(4))[0]
            if index >= len(self.refs) or self.refs[index] is None:
                raise _PyiError(f'a bad marshal back reference at {at}')
            return self.refs[index]
        if kind == 'c':
            node = _MarshalCode()
            self.take(20)                    # argcount, posonly, kwonly, stacksize, flags
            self.obj(depth + 1)              # the bytecode
            node.consts = self.obj(depth + 1)
            node.names = self.obj(depth + 1)
            self.obj(depth + 1)              # localsplusnames
            self.obj(depth + 1)              # localspluskinds
            node.filename = self.obj(depth + 1)
            name = self.obj(depth + 1)
            node.qualname = self.obj(depth + 1)
            node.qualname = node.qualname if isinstance(node.qualname, str) else name
            node.line = self.i32()
            self.obj(depth + 1)              # linetable
            self.obj(depth + 1)              # exceptiontable
            return node
        raise _PyiError(f'marshal type {kind!r} at {at} is not accepted')


def _pyz_strings(data):
    """The code objects of one inflated PYZ module in source order (a parent before its nested
    code), each with its qualified name, first line, string constants and names."""
    walk = _MarshalWalk(memoryview(data))
    root = walk.obj()
    if not isinstance(root, _MarshalCode):
        raise _PyiError('the module data is not a code object')
    codes, budget = [], [IMAGE_TEXT_MAX_STRINGS]

    def strings(values, out):
        for v in values:
            if isinstance(v, str):
                if budget[0] <= 0:
                    return
                budget[0] -= 1
                out.append(_image_render(v[:IMAGE_TEXT_MAX_TOKEN].encode('utf-8', 'replace')))
            elif isinstance(v, tuple) and not isinstance(v, _MarshalCode):
                strings(v, out)

    def visit(node):
        entry = {'code': node.qualname, 'line': node.line, 'consts': [], 'names': []}
        strings(node.consts if isinstance(node.consts, tuple) else (), entry['consts'])
        strings(node.names if isinstance(node.names, tuple) else (), entry['names'])
        codes.append(entry)
        for value in node.consts if isinstance(node.consts, tuple) else ():
            if isinstance(value, _MarshalCode):
                visit(value)

    visit(root)
    return {'filename': root.filename if isinstance(root.filename, str) else None,
            'codes': codes, 'strings_truncated': budget[0] <= 0}


def _image_resolved_file(view, path):
    """(report, src): an exact image path resolved inside the root; src is set for a file."""
    report = {'path': path}
    final_path, final, hops, error = view.resolve(path, follow_last=True)
    if error:
        return dict(report, present=False, refused=error), None
    if final is None:
        return dict(report, present=False, dangling=True) if hops else \
            dict(report, present=False), None
    report['present'] = True
    if hops:
        report['real_path'] = '/' + final_path
    report.update(_node_fields(final))
    if final.kind != 'file':
        return dict(report, refused=f'a {final.kind}, not a file'), None
    return report, final.src


def _image_text_glob(view, request):
    """(files, skipped, total): the union paths a path glob matches, in path order."""
    rx, files, skipped, total = request['_rx_path'], [], [], 0
    for path in sorted(p for p in view.nodes if p and rx.fullmatch(p)):
        node = view.nodes[path]
        if node.kind == 'dir':
            continue
        if node.kind != 'file':
            total += 1
            if len(skipped) < IMAGE_TEXT_MAX_SKIPPED:
                skipped.append(dict({'path': '/' + path, 'type': node.kind},
                                    **({'link_target': node.target} if node.target else {})))
            continue
        files.append((path, node))
    return files, skipped, total


def _image_text_file_job(out, request, context, max_matches):
    """The job that fills one searched file's entry (search or distinct) from its bytes."""
    def job(data, sha, size, _cache):
        out.update(sha256=sha)
        if data is None:
            out['refused'] = 'larger than the text bound'
            return
        _image_text_body(out, data, request, context, max_matches, lines=_IMAGE_NUL not in data)
    return job


def _image_text_body(out, data, request, context, max_matches, lines):
    out['binary'] = not lines
    if request['op'] == 'search':
        found, total, capped = _image_matches(data, request['_rx'], context, max_matches, lines)
        out.update(matches_total=total, matches=found)
    else:
        counts, total, capped, full = _image_distinct(data, request['_rx'])
        out.update(matches_total=total, _counts=counts)
        if full:
            out['distinct_held_capped'] = True
    if capped:
        out['count_capped'] = True


def _image_pyz_job(out, request, context, max_matches):
    """The job for EXE!MODULES requests: list, search, distinct or strings over PYZ modules."""
    def job(data, sha, size, cache):
        out['exe'].update(sha256=sha)
        if data is None:
            out['refused'] = 'the executable is larger than the text bound'
            return
        if 'archive' not in cache:
            try:
                cache['archive'] = pyi_archive(data)
            except _PyiError as exc:
                cache['archive'] = str(exc)
        archive = cache['archive']
        if isinstance(archive, str):
            out['refused'] = f'not a readable PyInstaller executable: {archive}'
            return
        out['pyinstaller'] = {k: v for k, v in archive.items() if not k.startswith('_')
                              and k != 'modules'}
        out['pyinstaller']['modules'] = len(archive['modules'])
        names = sorted(n for n in archive['modules'] if fnmatch.fnmatchcase(n, request['modules']))
        out['modules_total'] = len(names)
        limit = IMAGE_TEXT_MAX_STRINGS_MODULES if request['op'] == 'strings' else \
            IMAGE_TEXT_MAX_LIST if request['op'] == 'list' else IMAGE_TEXT_MAX_FILES
        if len(names) > limit:
            out['modules_truncated'] = True
        if request['op'] == 'strings' and archive['python'] not in PYI_CODE_VERSIONS:
            out['refused'] = f'python {archive["python"]}: the marshal walker knows ' \
                             f'{list(PYI_CODE_VERSIONS)}'
            return
        modules = cache.setdefault('modules', {})
        for name in names[:limit]:
            kind, _, length = archive['modules'][name]
            entry = {'path': f'{request["exe"]}!{name}', 'kind': PYI_PYZ_KINDS.get(kind, kind),
                     'compressed': length}
            out['files'].append(entry)
            if request['op'] == 'list':
                continue
            if name not in modules:
                modules[name] = pyz_module(archive, name)
            body = modules[name]
            if isinstance(body, str):
                entry['refused'] = body
                continue
            entry.update(size=len(body), sha256=hashlib.sha256(body).hexdigest())
            if request['op'] == 'strings':
                try:
                    entry.update(_pyz_strings(body))
                except (_PyiError, struct.error, UnicodeDecodeError, ValueError) as exc:
                    entry['refused'] = f'marshal walk: {exc}'
            else:
                _image_text_body(entry, body, request, context, max_matches, lines=False)
    return job


def _image_text_plan(view, text, jobs):
    """The output skeleton of every text request, and the jobs (by layer entry) that fill it
    from file content in the second pass."""
    out = {key: [] for key in ('lists', 'excerpts', 'searches', 'distinct', 'strings')}
    slot = {'list': 'lists', 'excerpt': 'excerpts', 'search': 'searches', 'distinct': 'distinct',
            'strings': 'strings'}
    context, max_matches = text['context'], text['max_matches']

    def add(src, job):
        jobs.setdefault(src, []).append(job)

    for request in text['requests']:
        op = request['op']
        entry = {k: v for k, v in request.items() if not k.startswith('_') and k != 'op'}
        out[slot[op]].append(entry)
        if op == 'excerpt':
            report, src = _image_resolved_file(view, request['path'])
            entry.update(report, start=request['start'], end=request['end'])
            if src is not None:
                def excerpt_job(data, sha, size, _cache, entry=entry, request=request):
                    entry['sha256'] = sha
                    entry.update(_image_excerpt(data, request['start'], request['end'])
                                 if data is not None else {'refused': 'larger than the text bound'})
                add(src, excerpt_job)
            continue
        if 'exe' in request:
            report, src = _image_resolved_file(view, request['exe'])
            entry.update(exe=report, files=[])
            if src is not None:
                add(src, _image_pyz_job(entry, request, context, max_matches))
            continue
        files, skipped, not_files = _image_text_glob(view, request)
        if op == 'list':
            listed = [dict({'path': '/' + p}, **_node_fields(n)) for p, n in files]
            listed += skipped
            listed.sort(key=lambda e: e['path'])
            entry.update(total=len(files) + not_files, entries=listed[:IMAGE_TEXT_MAX_LIST],
                         truncated=len(files) + not_files > IMAGE_TEXT_MAX_LIST
                         or not_files > len(skipped))
            continue
        entry.update(files_total=len(files), files=[], skipped=skipped, skipped_total=not_files)
        if len(files) > IMAGE_TEXT_MAX_FILES:
            entry['files_truncated'] = True
        for path, node in files[:IMAGE_TEXT_MAX_FILES]:
            item = dict({'path': '/' + path}, **_node_fields(node))
            entry['files'].append(item)
            add(node.src, _image_text_file_job(item, request, context, max_matches))
    return out


def _image_text_finish(out):
    """Request-level caps, applied in path order once every file is read."""
    for entry in out['searches']:
        reported, total = 0, 0
        for item in entry['files']:
            total += item.get('matches_total', 0)
            keep = max(0, IMAGE_TEXT_MAX_REQUEST_MATCHES - reported)
            if len(item.get('matches', ())) > keep:
                item['matches_omitted'] = len(item['matches']) - keep
                item['matches'] = item['matches'][:keep]
            reported += len(item.get('matches', ()))
        entry.update(matches_total=total, matches_reported=reported,
                     files_with_matches=sum(1 for i in entry['files'] if i.get('matches_total')))
    for entry in out['distinct']:
        merged, files = {}, {}
        for item in entry['files']:
            counts = item.pop('_counts', {})
            for key, n in counts.items():
                merged[key] = merged.get(key, 0) + n
                files[key] = files.get(key, 0) + 1
        keys = sorted(merged)
        entry.update(distinct_total=len(keys),
                     distinct_truncated=len(keys) > IMAGE_TEXT_MAX_DISTINCT,
                     matches_total=sum(i.get('matches_total', 0) for i in entry['files']),
                     values=[{'value': _image_render(k), 'count': merged[k], 'files': files[k]}
                             for k in keys[:IMAGE_TEXT_MAX_DISTINCT]])
    return out


def image_inspect(ctx, path_specs, text=None):
    """image-inspect: the requested paths of the staged, re-verified agent-server image; with
    text (parse_image_text_requests), also the bounded text requests."""
    t0 = time.time()
    specs = [parse_image_path_spec(s) for s in path_specs]
    if text is None and (not specs or len(specs) > IMAGE_INSPECT_MAX_PATHS):
        raise Refused('REFUSED', f'image-inspect needs 1 to {IMAGE_INSPECT_MAX_PATHS} --path')
    if text is not None and (len(specs) > IMAGE_INSPECT_MAX_PATHS or
                             not (specs or text.get('requests'))):
        raise Refused('REFUSED', f'image-inspect needs at most {IMAGE_INSPECT_MAX_PATHS} --path '
                      'and at least one --path or text request')
    lock, lock_rel, lock_sha = provision_lock(ctx)
    items = provision_items(lock)
    image = provision_image(lock)
    staged_dir = Path(ctx.state_dir) / 'provision' / lock_sha
    _plain_dir(staged_dir)
    if not staged_dir.is_dir():
        raise Refused('REFUSED', f'{staged_dir}: no stage for this lock; run provision-fetch')
    verified = verify_staged(staged_dir, lock_sha, items, image)
    with open(staged_dir / 'image' / PROVISION_IMAGE_ARCHIVE, 'rb') as handle:
        read = read_image_archive(handle, image, specs, text) if text is not None else \
            read_image_archive(handle, image, specs)
    return dict(read, operation='image-inspect', result='inspected', labels=labels(ctx.profile),
                lock={'path': lock_rel, 'sha256': lock_sha},
                image={k: image.get(k) for k in ('repository', 'index_digest', 'manifest_digest',
                                                  'config_digest')},
                verify=verified, seconds=round(time.time() - t0, 1))


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
                                             ('upload', 'root_step', 'facts', 'moby', 'image',
                                              'agent_server')):
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


def agent_server_directories(profile):
    """guest_storage directories of the Agent Server (role agent-server), parents first."""
    dirs = [d for d in (profile.get('guest_storage') or {}).get('directories') or []
            if d.get('role') == 'agent-server']
    return sorted(dirs, key=lambda d: d['path'].count('/'))


def agent_server_manifest(profile, files):
    """The manifest's agent_server section (F-04.1 slice (c)): the uploaded release binary
    by name and sha256, the non-secret config, the user's home, the scratch directories
    with their modes and the declared listener. No secret: the root step generates them."""
    server = profile['provisioning']['agent_server']
    name = server['binary']['upload_name']
    binary = [f for f in files if f['role'] == 'release-binary' and f['name'] == name]
    if len(binary) != 1:
        raise Refused('REFUSED', f'provisioning.agent_server.binary.upload_name {name!r} is not '
                      'the one release-binary file of the lock')
    return {'binary': {'name': name, 'sha256': binary[0]['sha256']},
            'config': server['config']['content'],
            'home': server['user']['home'],
            'directories': [{'path': d['path'], 'mode': d['mode']}
                            for d in agent_server_directories(profile)],
            'listener': {'address': server['listener']['address'],
                         'port': server['listener']['port']}}


def build_provision_manifest(ctx, egress_falsification=False, inference=False):
    """The seeded manifest of a provisioned instance, from the committed lock and the
    re-verified host stage (provision-fetch): every file to upload with its role, size
    and sha256, the packages, the image (locked config digest, the archive's tags, the
    local immutable tag) and the declared daemon.json. Deterministic for one stage.
    ``inference`` (decision 0015, the opt-in composition) merges the composition's
    daemon.json keys (bip, dns); without it the manifest is the ordinary one, byte for
    byte."""
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
    agent_server = agent_server_manifest(ctx.profile, files)
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
        'docker': {'server_version': moby['server_version'],
                   'daemon_json': declared_daemon_json(ctx.profile, inference),
                   'sysctl': moby['sysctl']['content'],
                   'containerd_config': moby['containerd_config']['content']},
        'agent_server': agent_server,
    }
    if egress_falsification:
        # S-01.4 fix-forward: the root step enables the route-present request (validation only)
        manifest['validation'] = {'egress_route': True, 'gateway': EGRESS_ROUTE_GATEWAY,
                                  'ceiling_s': EGRESS_ROUTE_CEILING_S}
    data = (json.dumps(manifest, indent=1, sort_keys=True) + '\n').encode('ascii')
    digest = hashlib.sha256(data).hexdigest()
    return {'bytes': data, 'sha256': digest, 'manifest': manifest, 'sources': sources,
            'record': {'manifest_sha256': digest, 'lock_sha256': lock_sha,
                       'image_id': image['config_digest'],
                       'local_tag': conf['image']['local_tag'],
                       'files': len(files), 'bytes': sum(f['size'] for f in files),
                       'staged_dir': posix(staged_dir), 'stage_verify_seconds':
                       verified['seconds'],
                       'agent_server': {'version': conf['agent_server'].get('version'),
                                        'binary_sha256': agent_server['binary']['sha256']},
                       'egress_falsification': bool(egress_falsification)}
            | ({'inference': True} if inference else {})}


# ---------------------------------------------------------------- inference composition (S-03.2)
#
# Decision 0015 section 4: the guest inference endpoint is a TCP listener on the docker0 gateway
# address, owned by the guest's sshd as a remote forward the dispatcher holds; its guest
# composition (the sshd forwarding directives, the container guard's one ACCEPT, daemon.json's
# bip and dns) is opt-in per guest (create --provision --inference) and declared in the
# profile's network.inference_composition. Applying it to a guest is the Owner's guest hardening
# act; without the option the seed, the manifest and every guest-visible file are the ordinary
# ones. Inspect verifies whichever state the launch record names.

INFERENCE_DROPIN_CHECK = 'sshd drop-in (inference composition, decision 0015)'
INFERENCE_SSHD_CHECK = 'sshd -T forwarding directives (inference composition)'
INFERENCE_LISTENER_CHECK = 'inference endpoint listener (decision 0015)'
INFERENCE_KEY_CHECK = 'provider key fingerprint (decision 0015)'
INFERENCE_KEY_SEARCH_CHECK = 'provider key itself, raw and encoded (synthetic key, S-03.2)'
INFERENCE_SSHD_KEYS = ('allowtcpforwarding', 'gatewayports', 'permitlisten')
_SEED_FILES = {}


def inference_config(profile):
    conf = (profile.get('network') or {}).get('inference_composition')
    return conf if isinstance(conf, dict) else {}


def inference_endpoint(profile):
    """(address, port) of the profile's inference endpoint, or (None, None)."""
    for entry in (profile.get('network') or {}).get('endpoints') or []:
        if isinstance(entry, dict) and entry.get('class') == 'inference':
            return entry.get('guest_address'), entry.get('guest_port')
    return None, None


def inference_opted(record):
    """True for an instance created with create --provision --inference."""
    return isinstance(record.get('inference'), dict) and \
        record['inference'].get('composition') == 'inference'


def declared_daemon_json(profile, inference):
    """The daemon.json of a provisioned instance: the profile's, plus the inference
    composition's keys for an opted-in one."""
    moby = ((profile.get('provisioning') or {}).get('moby') or {}).get('daemon_json')
    if not inference:
        return moby
    extra = inference_config(profile).get('daemon_json')
    if not isinstance(moby, dict) or not isinstance(extra, dict) or not extra:
        raise Refused('REFUSED', 'the profile declares no inference composition daemon.json')
    return dict(moby, **extra)


def declared_seed_files(profile, inference):
    """{path: content} of the user-data write_files the instance was seeded with, from the
    pinned templates of this checkout (and the pinned overlay when ``inference``)."""
    seed = (profile.get('boot_inputs') or {}).get('seed')
    key = (json.dumps([seed, inference_config(profile).get('seed_overlay'),
                       inference_endpoint(profile)], sort_keys=True, default=str), bool(inference))
    if key not in _SEED_FILES:
        gen = load_seed_generator()
        try:
            templates = gen.read_templates(profile, REPO)
            if inference:
                templates, _ = gen.compose_templates(profile, REPO, templates, ('inference',))
        except gen.Refused as exc:
            raise Refused('REFUSED', f'the declared seed cannot be composed: {exc}') from None
        _SEED_FILES[key] = load_profile_checker().write_files_blocks(templates['user-data'])
    return _SEED_FILES[key]


def inference_record(profile, seed):
    """The launch record's inference block of an opted-in instance (decision 0015)."""
    conf = inference_config(profile)
    composed = (seed.get('compositions') or {}).get('inference') or {}
    if composed.get('overlay_sha256') != (conf.get('seed_overlay') or {}).get('sha256'):
        raise Refused('REFUSED', 'seed: the inference overlay digest differs from the profile pin')
    address, port = inference_endpoint(profile)
    return {'composition': 'inference', 'status': str(conf.get('status', '')).split(':', 1)[0],
            'overlay': dict(conf.get('seed_overlay') or {}),
            'endpoint': {'address': address, 'port': port},
            'daemon_json': conf.get('daemon_json'),
            'container_guard_allow': (conf.get('container_guard_allow') or {}).get('rule')}


def inference_forward_path(profile, instance_dir):
    record = str((inference_config(profile).get('forward_session') or {}).get('record', ''))
    if not record.startswith('{instance_dir}/'):
        return None
    return Path(instance_dir) / record[len('{instance_dir}/'):]


# ---------------------------------------------------------------- inference forward session (S-03.2)
#
# Decision 0015 sections 4.1, 4.3 and 4.4 (S-03.2 slice 3): the dispatcher holds the guest's inference
# endpoint as an SSH remote forward over the management hostfwd, ssh -N -R <endpoint>:127.0.0.1:<broker
# inference port>, with the per-instance key, the profile's ssh_client_options and the forward's own
# options (network.inference_composition.forward_session). A detached holder process starts ssh, writes
# {instance_dir}/inference-forward.json once ssh reports the forward established, waits on ssh and removes
# the record when the session ends; every reader trusts a record only while its ssh process runs. start is
# idempotent (a live session is returned, a stale record replaced); re-establishment is an explicit re-run,
# never an automatic retry loop. Nothing here runs without an Owner act: a forward is the guest-to-host path
# (A3), on a guest with the composition (A4), to the broker's host listener (A2).

FORWARD_SCHEMA = 'ai-engineering-harness/profiles/inference-forward/v1'
FORWARD_OPERATION = 'inference-forward'
FORWARD_ACTIONS = ('start', 'status', 'stop')
FORWARD_MARGIN_S = 15          # the parent's ceiling beyond the holder's own establishment ceiling
FORWARD_STOP_WAIT_S = 30       # ceiling for ssh, then its holder, to exit after stop
FORWARD_KEEP_LINES = 40        # ssh's non-debug stderr lines the holder keeps for its log
FORWARD_LOG = 'inference-forward.log'
_MANAGED = object()


def inference_control():
    """integrations/inference/inference_control.py, the dispatcher's side of the broker (its ports,
    its control client, the token fingerprint), loaded once."""
    return _inference_module('aieh_inference_control', 'inference_control.py')


def key_search():
    """integrations/inference/inference_key_search.py, S-03.2's provider-key containment search
    (standard library only; it imports nothing of the broker), loaded once."""
    return _inference_module('aieh_inference_key_search', 'inference_key_search.py')


def dispatch_transport():
    """integrations/dispatch/guest_transport.py, the dispatcher's live transport over GuestApi (E-01.3.3; standard
    library only, it imports nothing of this module), loaded once."""
    return _inference_module('aieh_dispatch_guest_transport', 'guest_transport.py', 'dispatch')


def acp_qualification():
    """integrations/dispatch/acp_qualification.py, the S-03.3 qualification create and its admission (it loads
    the broker by path for its token and model grammars), loaded once."""
    return _inference_module('aieh_dispatch_acp_qualification', 'acp_qualification.py', 'dispatch')


def containment():
    """integrations/dispatch/conversation_containment.py, S-03.3 slice 1's collector and verdicts (standard library
    only; the same file is sent to the guest as the collector), loaded once."""
    return _inference_module('aieh_dispatch_conversation_containment', 'conversation_containment.py', 'dispatch')


def _inference_module(name, file, package='inference'):
    module = sys.modules.get(name)
    if module is None:
        path = REPO / 'integrations' / package / file
        spec = importlib.util.spec_from_file_location(name, path)
        module = sys.modules[name] = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except BaseException:
            del sys.modules[name]
            raise
    return module


def read_provider_key(stream, expected):
    """The synthetic qualification key of S-03.2's provider-key search from ``stream`` (one line
    of standard input, never argv): never a terminal, the launcher's synthetic shape, and the key
    of ``expected``, the broker start receipt's fingerprint. A refusal never repeats what was
    read. The real key is never read here (its containment is S-03.3's)."""
    ks = key_search()
    try:
        if not GITEA_FINGERPRINT.match(str(expected)):
            raise ks.SearchError('FINGERPRINT_INVALID', 'give --provider-key-fingerprint too')
        if stream.isatty():
            raise ks.SearchError('KEY_STDIN_TTY', 'standard input is a terminal')
        key = ks.read_key(io.StringIO(stream.readline(ks.KEY_LIMIT + 3)))
        ks.check_fingerprint(key, expected)
    except ks.SearchError as exc:
        raise Refused('REFUSED', f'--provider-key-stdin: {exc}') from None
    return key


def provider_key_search(key, tar_bytes, host_files):
    """S-03.2's provider-key search of the P5 collection (the guest's files, process
    environments and records, as collect_p5 gathers them) and of its host files: the
    synthetic key held in memory, raw and in its encodings, never by fingerprint; its positive
    controls in memory. The report carries counts and the fingerprint only."""
    search = key_search().Search(key)
    search.tar('guest collection (P5: files, process environments, records)', tar_bytes)
    for label, path in sorted(host_files.items()):
        search.file(f'host {label}', path)
    search.controls()
    return search.report()


def forward_answers_search(key, answers):
    """S-03.2's provider-key search of what crossed the forward to the job: each answer the
    endpoint gave the job (and the guest login), whole, as received in the guest."""
    search = key_search().Search(key)
    for label, data in answers:
        search.http(f'answer received in the guest: {label}', data)
    search.controls()
    return search.report()


def key_search_summary(report):
    """The check's view of a provider-key search report: counts only."""
    return {'verdict': report.get('verdict'), 'bytes_searched': report.get('bytes_searched'),
            'controls': {k: (report.get('controls') or {}).get(k) for k in ('valid', 'cases')},
            'surfaces': [{k: s.get(k) for k in ('label', 'bytes_total', 'complete', 'found')}
                         for s in report.get('surfaces') or []]}


class BrokerAccess:
    """The broker as the dispatcher reaches it: its two listener ports (components.inference_broker of
    config.yml, through the broker's own loader) and a client of its control listener. ``component``
    and ``client`` stand in for config.yml and the listener in tests (never the managed ones)."""

    def __init__(self, component=_MANAGED, client=None):
        ic = inference_control()
        try:
            raw = ic.managed_component() if component is _MANAGED else component
            self.ports = ic.dispatcher_ports(raw)
            self.client = client or ic.ControlClient(self.ports['control_port'])
        except (ic.ControlError, ic.broker.paths.PathsError) as exc:
            raise Refused('BROKER_CONFIG', f'components.inference_broker: {exc}') from None

    def call(self, method, *args):
        ic = inference_control()
        try:
            return getattr(self.client, method)(*args)
        except ic.ControlError as exc:
            raise Refused('BROKER', f'the broker\'s control listener: {exc}',
                          {'code': exc.code, 'status': exc.status}) from None


def forward_config(profile):
    return inference_config(profile).get('forward_session') or {}


def forward_process(session):
    """The recorded ssh process of a forward session while it runs (its pid, binary and creation time as
    recorded), else None."""
    if os.name != 'nt':
        raise Refused('REFUSED', 'process control is implemented for Windows only')
    try:
        proc = WinProcess(int(session['pid']))
    except (OSError, KeyError, TypeError, ValueError):
        return None
    try:
        if proc.alive() and same_path(proc.image(), session['binary']) and \
                abs(proc.created() - float(session['created_epoch'])) < 1.0:
            return proc
    except (OSError, KeyError, TypeError, ValueError):
        pass
    proc.close()
    return None


def forward_state(profile, instance_dir):
    """{'path', 'session', 'held', 'stale'} of an instance's forward-session record, changing nothing:
    held while the record names a running ssh process; stale (why) for a record whose process is gone
    or that is not a record of this profile's shape."""
    path = inference_forward_path(profile, instance_dir)
    out = {'path': None if path is None else posix(path), 'session': None, 'held': False,
           'stale': None}
    if path is None or not path.is_file():
        return out
    try:
        session = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(session, dict) or session.get('schema') != FORWARD_SCHEMA or \
                sorted(session) != sorted(forward_config(profile).get('fields') or []):
            raise ValueError('not a forward-session record of this profile')
    except (OSError, ValueError) as exc:
        out['stale'] = f'unreadable: {exc}'[:300]
        return out
    out['session'] = session
    proc = forward_process(session)
    if proc is None:
        out['stale'] = 'its ssh process is gone'
    else:
        proc.close()
        out['held'] = True
    return out


def remove_stale_forward(profile, instance_dir, state):
    """Remove a stale forward-session record (never a held one); returns what was removed."""
    if state['held'] or state['stale'] is None:
        return None
    try:
        Path(state['path']).unlink()
    except FileNotFoundError:
        pass
    return {'why': state['stale'], 'session': state['session']}


def forward_argv(profile, ssh, broker_port):
    """The forward session's ssh command line: the per-instance channel (ssh_client_options, the
    harness's options, -i, -p), the forward's own options, -R, then the destination."""
    address, port = inference_endpoint(profile)
    options = forward_config(profile).get('ssh_options')
    problems = load_profile_checker().forward_option_problems(options)
    if problems or address is None or port is None:
        raise Refused('REFUSED', f'the profile declares no usable forward session: {problems}')
    base = ssh.argv('agent', [])               # checks the key, known_hosts and ssh -G first
    return base[:-1] + list(options) + ['-R', f'{address}:{port}:{LOOPBACK}:{broker_port}',
                                        base[-1]]


def write_json_new(path, data):
    """Write a JSON file that appears whole or not at all, and never over an existing one."""
    path = Path(path)
    tmp = path.with_name(f'{path.name}.{secrets.token_hex(4)}.partial')
    write_json_exclusive(tmp, data)
    try:
        os.rename(tmp, path)                      # Windows: FileExistsError when it exists
    except BaseException:
        tmp.unlink()
        raise


def forward_hold(spec_text, out=None, pid=None):
    """inference-forward-hold (internal, started detached by inference-forward start): start ssh, wait
    for its establishment line (or its end, or the ceiling), write the record, report one JSON line on
    standard output, then wait on ssh and remove the record when the session ends. ``pid`` stands
    in for the holder's own process id in tests that run it in a thread."""
    out = out or sys.stdout
    holder_pid = os.getpid() if pid is None else pid
    spec = json.loads(base64.b64decode(spec_text).decode('utf-8'))
    path = Path(spec['record'])
    want = f"remote forward success for: listen {spec['listen']}, connect {spec['connect']}"
    proc = subprocess.Popen(spec['argv'], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE, creationflags=_no_window().no_window_flags())
    decided, kept, state = threading.Event(), [], {'established': False}

    def drain():
        for raw in proc.stderr:
            line = raw.decode('utf-8', 'replace').rstrip('\r\n')
            if not state['established'] and want in line:
                state['established'] = True
                decided.set()
            elif not line.startswith('debug') and len(kept) < FORWARD_KEEP_LINES:
                kept.append(line)
        decided.set()                             # end of stderr: ssh has ended

    def report(result, **extra):
        out.write(json.dumps(dict(extra, result=result), sort_keys=True) + '\n')
        out.flush()

    def keep_log(message):
        with open(spec['log'], 'a', encoding='utf-8', newline='\n') as handle:
            handle.write(f'{utc_now()} {message}\n' + ''.join(f'  ssh: {k}\n' for k in kept))
        kept.clear()

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    in_time = decided.wait(spec['ceiling'])
    if not state['established']:
        if proc.poll() is None:
            proc.kill()
        rc = proc.wait()
        reader.join(FORWARD_STOP_WAIT_S)
        proc.stderr.close()
        report('failed', rc=rc, stderr=kept[-20:],
               reason='ssh ended before the forward was established' if in_time
               else f'no establishment within {spec["ceiling"]} s')
        keep_log(f'ssh {proc.pid}: not established (rc {rc})')
        return 1
    handle = WinProcess(proc.pid)
    try:
        created = handle.created()
    finally:
        handle.close()
    session = {'schema': FORWARD_SCHEMA, 'instance': spec['instance'], 'pid': proc.pid,
               'binary': spec['argv'][0], 'created_epoch': created, 'holder_pid': holder_pid,
               'started_at': utc_now(), 'ports': spec['ports'], 'argv': spec['argv']}
    try:
        write_json_new(path, session)
    except FileExistsError:
        proc.kill()
        proc.wait()
        reader.join(FORWARD_STOP_WAIT_S)
        proc.stderr.close()
        report('already-held')
        return 1
    report('held', session=session)
    keep_log(f'ssh {proc.pid}: forward established ({spec["listen"]} -> {spec["connect"]})')
    rc = proc.wait()
    reader.join(FORWARD_STOP_WAIT_S)
    proc.stderr.close()
    try:
        current = json.loads(path.read_text(encoding='utf-8'))
        if current.get('pid') == proc.pid and current.get('holder_pid') == holder_pid:
            path.unlink()
    except (OSError, ValueError):
        pass
    keep_log(f'ssh {proc.pid}: session ended (rc {rc}); its record is removed')
    return 0


def forward_spawn(spec, cwd):
    """The holder of one forward session (the dispatcher's process for its whole life), in its own
    process group and with a console that no window shows: never DETACHED_PROCESS, under which the ssh
    it starts would open a console window of its own."""
    text = base64.b64encode(json.dumps(spec).encode('utf-8')).decode('ascii')
    argv = [sys.executable, '-I', '-B', str(Path(__file__).resolve()), 'inference-forward-hold',
            '--spec', text]
    flags = NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
    return subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, cwd=str(cwd), close_fds=True,
                            creationflags=flags)


def read_line_within(stream, ceiling):
    """One line of ``stream``, or None when none arrives within ``ceiling`` seconds (a bound on a hang:
    the line is the holder's own completion signal)."""
    box = []
    reader = threading.Thread(target=lambda: box.append(stream.readline()), daemon=True)
    reader.start()
    reader.join(ceiling)
    return box[0] if box else None


def forward_start(ctx, name, idir, record, state, broker_port=None, broker=None, spawn=None,
                  ssh=None):
    """Hold the forward session of one opted-in instance (idempotent)."""
    if state['held']:
        return {'result': 'held', 'existing': True, 'session': state['session']}
    ic = inference_control()
    access = broker or BrokerAccess()
    try:
        target = ic.forward_target(access.ports, broker_port)
    except ic.ControlError as exc:
        raise Refused('REFUSED', str(exc), {'code': exc.code}) from None
    status = access.call('status')
    if ((status.get('listeners') or {}).get('inference') or {}).get('port') != target:
        raise Refused('BROKER_NOT_READY', f'the broker\'s inference listener is not on '
                      f'{LOOPBACK}:{target} (decision 0015 section 4.4: the broker first)',
                      {'listeners': status.get('listeners')})
    if not running_process(idir, record['binary']):
        raise Refused('NOT_RUNNING', f'{name} is not running')
    replaced = remove_stale_forward(ctx.profile, idir, state)
    ssh = ssh or Ssh(ctx.profile, idir, record['ports']['ssh'])
    argv = forward_argv(ctx.profile, ssh, target)
    address, port = inference_endpoint(ctx.profile)
    ceiling = forward_config(ctx.profile).get('establish_ceiling_s')
    spec = {'argv': argv, 'record': str(inference_forward_path(ctx.profile, idir)),
            'log': str(idir / FORWARD_LOG), 'instance': name, 'listen': f'{address}:{port}',
            'connect': f'{LOOPBACK}:{target}', 'ceiling': ceiling,
            'ports': {'endpoint': {'address': address, 'port': port},
                      'broker': {'address': LOOPBACK, 'port': target},
                      'hostfwd': {'address': LOOPBACK, 'port': record['ports']['ssh']}}}
    holder = (spawn or forward_spawn)(spec, idir.parent)
    line = read_line_within(holder.stdout, ceiling + FORWARD_MARGIN_S)
    try:
        reply = json.loads(line) if line else None
    except ValueError:
        reply = None
    finally:
        holder.stdout.close()
    if not isinstance(reply, dict):
        holder.kill()
        raise Refused('FORWARD_FAILED', f'the holder reported nothing within '
                      f'{ceiling + FORWARD_MARGIN_S} s; see {FORWARD_LOG}')
    if reply.get('result') == 'held':
        return {'result': 'held', 'existing': False, 'replaced_stale': replaced,
                'session': reply.get('session')}
    if reply.get('result') == 'already-held':
        again = forward_state(ctx.profile, idir)
        if again['held']:
            return {'result': 'held', 'existing': True, 'session': again['session']}
    raise Refused('FORWARD_FAILED', f'the forward was not established: {reply.get("reason")}', reply)


def forward_stop(profile, idir, state):
    """End a held forward session: terminate its ssh; its holder removes the record (or this does)."""
    if not state['held']:
        return {'result': 'not-held', 'removed_stale': remove_stale_forward(profile, idir, state)}
    session, path = state['session'], Path(state['path'])
    proc = forward_process(session)
    exited = True
    if proc is not None:
        try:
            proc.terminate()
            exited = proc.wait(FORWARD_STOP_WAIT_S)
        finally:
            proc.close()
    try:
        holder = WinProcess(int(session['holder_pid']))
    except (OSError, ValueError, TypeError):
        holder = None
    if holder is not None:
        try:
            holder.wait(FORWARD_STOP_WAIT_S)       # it removes the record, then exits
        finally:
            holder.close()
    removed_by = 'holder'
    if path.is_file():
        try:
            current = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            current = {}
        if current.get('pid') == session.get('pid'):
            try:
                path.unlink()
                removed_by = 'stop'
            except (FileNotFoundError, PermissionError):
                pass                              # the holder has it in hand (Windows sharing)
    return {'result': 'stopped' if exited else 'still-running', 'session': session,
            'record_removed_by': removed_by}


def inference_forward(ctx, name, action, broker_port=None, broker=None, spawn=None, ssh=None):
    """inference-forward --action start|status|stop (decision 0015 sections 4.1, 4.3 and 4.4) for an
    instance created with create --provision --inference; refused for any other. ``broker``,
    ``spawn`` and ``ssh`` stand in for the broker, the holder and the channel in tests."""
    if action not in FORWARD_ACTIONS:
        raise Refused('REFUSED', f'--action must be one of {", ".join(FORWARD_ACTIONS)}')
    idir = ctx.instance_dir(name)
    if not idir.is_dir():
        raise Refused('REFUSED', f'{name}: no such instance')
    record = read_launch_record(idir)
    if not inference_opted(record):
        raise Refused('REFUSED', f'{name} was not created with create --provision --inference: it '
                      'has no inference endpoint to forward')
    if inference_forward_path(ctx.profile, idir) is None:
        raise Refused('REFUSED', 'the profile declares no forward-session record')
    state = forward_state(ctx.profile, idir)
    result = {'operation': FORWARD_OPERATION, 'action': action, 'labels': labels(ctx.profile),
              'instance': name}
    if action == 'status':
        result.update(result='held' if state['held'] else 'not-held', session=state['session'],
                      removed_stale=remove_stale_forward(ctx.profile, idir, state))
    elif action == 'stop':
        result.update(forward_stop(ctx.profile, idir, state))
    else:
        result.update(forward_start(ctx, name, idir, record, state, broker_port, broker, spawn,
                                    ssh))
    result['record'] = write_record(idir, FORWARD_OPERATION, result)
    if result['result'] == 'still-running':
        raise Refused('STOP_FAILED', f'{name}: the forward\'s ssh process still runs', result)
    return result


def guard_rules_for(profile, record, tool):
    """The container guard's declared rules for one family: the inference composition's
    ACCEPT after the RETURN in its families when the instance opted in."""
    guard = ((admission_config(profile).get('network') or {}).get('guard') or {})
    rules = list(guard.get('rules') or [])
    if record is None or not inference_opted(record):
        return rules
    allow = inference_config(profile).get('container_guard_allow') or {}
    if tool in (allow.get('families') or []) and allow.get('rule'):
        return rules[:1] + [allow['rule']] + rules[1:]
    return rules


def _sshd_t(facts):
    inf = facts.get('inference') if isinstance(facts.get('inference'), dict) else {}
    lines = inf.get('sshd_t')
    if not isinstance(lines, list):
        return None
    out = {}
    for line in lines:
        key, _, value = str(line).partition(' ')
        out.setdefault(key, []).append(value)
    return out


def inference_listener_lines(profile, record, report, forward_recorded):
    """(allowed, others): root's listener lines on the inference endpoint's port. Allowed is
    the one sshd line on the declared address when the instance opted in and a forward
    session is recorded; every other line on that port is in others."""
    address, port = inference_endpoint(profile)
    procs = (inference_config(profile).get('sshd') or {}).get('listener_processes') or []
    lines = (report or {}).get('tcp_listeners')
    allowed, others = [], []
    for line in lines if isinstance(lines, list) else []:
        local = line.split()[3] if len(line.split()) > 3 else ''
        if port is None or local.rpartition(':')[2] != str(port):
            continue
        if inference_opted(record) and forward_recorded and local == f'{address}:{port}' and \
                _listener_process(line) in procs and not allowed:
            allowed.append(line)
        else:
            others.append(line)
    return allowed, others


def inference_checks(profile, record, obs):
    """Decision 0015 section 4.5, in the state the launch record names: {'P5': [...],
    'P7': [...]}. Off (every instance): the sshd drop-in is the ordinary one (no forwarding)
    and nothing listens on the endpoint's port. On: the drop-in is the composed one, sshd -T
    (boot facts) reports the declared directives, and the endpoint is listened on by sshd
    exactly when a forward session is recorded; the provider key's fingerprint is a P5
    needle. The guard chains and daemon.json are judged by the admission and Moby checks."""
    g = obs.get('guest', {})
    on = inference_opted(record)
    conf = inference_config(profile)
    sshd = conf.get('sshd') or {}
    dropin = sshd.get('dropin') or '/etc/ssh/sshd_config.d/10-aieh.conf'
    try:
        declared = declared_seed_files(profile, on).get(dropin)
    except Refused as exc:
        declared = None
        error = str(exc)
    else:
        error = None
    seen = (g.get('sshd_dropin') or {}).get('out')
    lines = lambda text: str(text).rstrip('\n').split('\n')      # noqa: E731
    p7 = [check(INFERENCE_DROPIN_CHECK,
                {'state': 'on' if on else 'off', 'dropin': declared if declared is not None
                 else error},
                seen, 'guest: cat 10-aieh.conf (agent) against the seeded write_files entry',
                None if declared is None or seen is None else lines(seen) == lines(declared))]
    out = {'P7': p7, 'P5': []}
    if not record.get('provisioning'):
        return out
    facts = _probe_json(obs, 'moby_facts') or {}
    report = conversation_report(obs)
    forward = obs.get('inference_forward') if isinstance(obs.get('inference_forward'), dict) else {}
    recorded = forward.get('recorded') is True
    allowed, others = inference_listener_lines(profile, record, report, recorded)
    address, port = inference_endpoint(profile)
    p7.append(check(INFERENCE_LISTENER_CHECK,
                    {'state': 'on' if on else 'off', 'endpoint': f'{address}:{port}',
                     'listener': 'sshd, exactly when a forward session is recorded'
                     if on else 'none'},
                    {'forward_session_recorded': recorded, 'listener': allowed,
                     'other_lines_on_the_port': others},
                    'on-demand conversation facts: ss -ltnpH (root, now); the instance '
                    'directory\'s forward-session record',
                    None if report is None else
                    not others and len(allowed) == (1 if on and recorded else 0)))
    if on:
        want = {k: [v] for k, v in (sshd.get('effective') or {}).items()}
        got = _sshd_t(facts)
        p7.append(check(INFERENCE_SSHD_CHECK, want,
                        None if got is None else {k: got.get(k) for k in INFERENCE_SSHD_KEYS},
                        'facts: sshd -T (root, at boot)',
                        None if got is None else
                        {k: got.get(k) for k in INFERENCE_SSHD_KEYS} == want))
    return out


CHECK_CLASSES[('profiles P7', INFERENCE_DROPIN_CHECK)] = (STABLE, None)
CHECK_CLASSES[('profiles P7', INFERENCE_SSHD_CHECK)] = (STABLE, None)
# whether a forward session is held depends on the moment; the verdict is still compared
CHECK_CLASSES[('profiles P7', INFERENCE_LISTENER_CHECK)] = (VOLATILE, None)
CHECK_CLASSES[('profiles P5', INFERENCE_KEY_CHECK)] = (STABLE, None)
CHECK_CLASSES[('profiles P5', INFERENCE_KEY_SEARCH_CHECK)] = (STABLE, None)


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
    ] + agent_server_probes(conf) + [('conversation_facts', conversation_facts_probe(conf))]


# The Agent Server probe, run as agent (F-04.1 slice (c)): the API on the guest's loopback
# with and without the session key, which it reads from its agent-readable file and never
# prints (its fingerprint only), and whether agent can open the secret files and the
# server's process environments (open only; nothing is read from them).
AGENT_SERVER_PROBE = r'''import errno, hashlib, http.client, json, subprocess, sys
key_path, host, port, user = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
paths = sys.argv[5:]
out = {}
def get(path, key=None):
    conn = http.client.HTTPConnection(host, port, timeout=30)
    try:
        conn.request('GET', path, headers={'X-Session-API-Key': key} if key is not None else {})
        r = conn.getresponse()
        body = r.read(1 << 20).decode('utf-8', 'replace')
        try:
            body = json.loads(body)
        except ValueError:
            body = body[:2000]
        return {'status': r.status, 'body': body}
    except OSError as exc:
        return {'error': errno.errorcode.get(exc.errno, str(exc))}
    finally:
        conn.close()
def can_open(path):
    try:
        with open(path, 'rb'):
            return 'READABLE'
    except OSError as exc:
        return errno.errorcode.get(exc.errno, str(exc))
try:
    with open(key_path, encoding='ascii') as handle:
        key = handle.read().strip()
    out['session_key_fingerprint'] = hashlib.sha256(
        b'aieh-secret-fingerprint/v1\n' + key.encode('ascii')).hexdigest()
except OSError as exc:
    key = None
    out['session_key_error'] = errno.errorcode.get(exc.errno, str(exc))
out['alive'] = get('/alive')
out['server_info'] = get('/server_info')
out['count_with_key'] = get('/api/conversations/count', key) if key else None
out['count_without_key'] = get('/api/conversations/count')
out['count_wrong_key'] = get('/api/conversations/count', 'x' * 43)
out['agent_open'] = {p: can_open(p) for p in paths}
pids = subprocess.run(['pgrep', '-u', user], capture_output=True, text=True).stdout.split()
out['server_environ_agent'] = sorted({can_open('/proc/' + p + '/environ') for p in pids})
out['server_processes'] = len(pids)
print(json.dumps(out, sort_keys=True))
'''


def agent_server_probes(conf):
    server = conf['agent_server']
    listener, key = server['listener'], server['session_key']
    files = [server['binary']['path'], server['config']['path'], server['secrets']['env_file'],
             key['guest_path'].rsplit('/', 1)[0], key['guest_path']]
    quoted = ' '.join(f"'{f}'" for f in files)
    secret_files = ' '.join(f"'{f}'" for f in (server['secrets']['env_file'], key['guest_path']))
    return [
        ('agent_server_api', f"timeout 120 python3 - '{key['guest_path']}' '{listener['address']}' "
                             f"'{listener['port']}' '{server['user']['name']}' {secret_files} "
                             f"<<'PYEOF'\n" + AGENT_SERVER_PROBE + 'PYEOF'),
        ('agent_server_files', f"stat -c '%n|%U|%G|%a|%F' -- {quoted}"),
        ('agent_server_config', f"cat '{server['config']['path']}'"),
    ]


# ---------------------------------------------------------------- on-demand conversation facts (F-04.2)

CONVERSATION_FACTS_SCHEMA = 'ai-engineering-harness/profiles/conversation-facts/v1'
CONVERSATION_FACTS_CEILING_S = 60      # bounds a hang of the root reporter (it takes ~1-3 s)

# Run as agent: create the request file (its existence is the reporter's only input), then
# wait on inotify in the report's directory until a report appears whose run started after
# the request was made (CLOCK_MONOTONIC, shared by every process of the guest). Prints the
# report, or an error object, as one JSON line.
CONVERSATION_FACTS_PROBE = r'''import ctypes, json, os, select, sys, time
request, report, ceiling = sys.argv[1], sys.argv[2], float(sys.argv[3])
def current():
    try:
        with open(report, encoding='utf-8') as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None
libc = ctypes.CDLL(None, use_errno=True)
fd = libc.inotify_init1(os.O_CLOEXEC)
if fd < 0 or libc.inotify_add_watch(fd, os.path.dirname(report).encode(), 0x80 | 0x100 | 0x8) < 0:
    print(json.dumps({'error': 'inotify', 'errno': ctypes.get_errno()})); sys.exit(3)
asked = time.monotonic()
try:
    os.close(os.open(request, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600))
except OSError as exc:
    print(json.dumps({'error': 'request', 'errno': exc.errno})); sys.exit(3)
deadline = asked + ceiling
while True:
    data = current()
    if isinstance(data, dict) and isinstance(data.get('started_monotonic'), (int, float)) and \
            data['started_monotonic'] > asked:
        print(json.dumps(data, sort_keys=True)); sys.exit(0)
    left = deadline - time.monotonic()
    if left <= 0:
        print(json.dumps({'error': 'ceiling', 'request_present': os.path.lexists(request),
                          'serial': (data or {}).get('serial')})); sys.exit(5)
    ready, _, _ = select.select([fd], [], [], min(5.0, left))
    if ready:
        os.read(fd, 65536)
'''


def conversations_config(conf):
    return ((conf or {}).get('agent_server') or {}).get('conversations') or {}


def conversation_facts_probe(conf):
    facts = conversations_config(conf).get('facts') or {}
    return (f"timeout {CONVERSATION_FACTS_CEILING_S + 30} python3 - '{facts.get('request')}' "
            f"'{facts.get('report')}' {CONVERSATION_FACTS_CEILING_S} <<'PYEOF'\n" +
            CONVERSATION_FACTS_PROBE + 'PYEOF')


def conversation_report(obs):
    """The on-demand conversation facts read by this inspect, or None."""
    data = _probe_json(obs, 'conversation_facts')
    return data if isinstance(data, dict) and data.get('schema') == CONVERSATION_FACTS_SCHEMA \
        else None


def conversation_owner(profile):
    """The owner label value the Agent Server puts on its conversation containers:
    sha256(conversations_path NUL OH_PERSISTENCE_DIR)[:24] (1.60.1 docker_runtime/registry.py
    DockerConversationRegistry.__init__); both are real directories, so resolved = declared."""
    server = (profile.get('provisioning') or {}).get('agent_server') or {}
    paths = f"{(server.get('config') or {}).get('content', {}).get('conversations_path')}\0" \
            f"{(server.get('environment') or {}).get('OH_PERSISTENCE_DIR')}"
    return hashlib.sha256(paths.encode()).hexdigest()[:24]


def memory_bytes(text):
    """Docker's reading of a memory size such as '4g' (binary units)."""
    match = re.fullmatch(r'(\d+)([bkmg]?)', str(text).lower())
    if not match:
        return None
    return int(match.group(1)) * {'': 1, 'b': 1, 'k': 1 << 10, 'm': 1 << 20, 'g': 1 << 30}[match.group(2)]


def conversation_hex(container):
    """The conversation id (32 hex digits) a container serves, from its event-store mount."""
    for mount in container.get('Mounts') or []:
        dest = str((mount or {}).get('Destination', ''))
        if dest.startswith('/var/openhands/conversations/'):
            tail = dest.rsplit('/', 1)[-1]
            if re.fullmatch(r'[0-9a-f]{32}', tail):
                return tail
    return None


def declared_container_mounts(profile, hex_id):
    conv = conversations_config(profile.get('provisioning'))
    return sorted((m['type'], m['source'].replace('{conversation_hex}', hex_id),
                   m['destination'].replace('{conversation_hex}', hex_id), bool(m['rw']))
                  for m in conv.get('mounts') or [])


def effective_container_mounts(container):
    return sorted((m.get('Type'), m.get('Source'), m.get('Destination'), bool(m.get('RW')))
                  for m in container.get('Mounts') or [] if isinstance(m, dict))


def forbidden_mount_sources(profile, container):
    """Mount sources outside the declared source root, or equal to or under a forbidden
    path (the Docker or containerd socket, Moby's data root, /etc/aieh, ...)."""
    conv = conversations_config(profile.get('provisioning'))
    root = str(conv.get('source_root', '')).rstrip('/') + '/'
    bad = []
    for _type, source, _dest, _rw in effective_container_mounts(container):
        source = str(source)
        under = [f for f in conv.get('forbidden_sources') or []
                 if source == f or source.startswith(f.rstrip('/') + '/')]
        if not source.startswith(root) or under:
            bad.append({'source': source, 'forbidden': under})
    return bad


def container_problems(profile, record, report, container):
    """One conversation container against provisioning.agent_server.conversations, decision
    0001 s2/s3 and decision 0006 item 3. Returns (problems, deviations): a problem fails the
    check; a deviation is recorded evidence (carried to S-01.3.x and E-01.2.2)."""
    server = (profile.get('provisioning') or {}).get('agent_server') or {}
    conv = server.get('conversations') or {}
    cfg = (server.get('config') or {}).get('content') or {}
    prov = record.get('provisioning') or {}
    config = container.get('Config') or {}
    host = container.get('HostConfig') or {}
    state = container.get('State') or {}
    user = report.get('server_user') or {}
    hex_id = conversation_hex(container)
    problems = []

    def need(name, ok, observed):
        if not ok:
            problems.append({'check': name, 'observed': observed})
    need('image (decision 0006 item 3)', container.get('Image') == prov.get('image_id'),
         container.get('Image'))
    need('configured image', config.get('Image') == cfg.get('conversation_image'), config.get('Image'))
    need('owner label', (config.get('Labels') or {}).get(conv.get('owner_label')) ==
         conversation_owner(profile), (config.get('Labels') or {}).get(conv.get('owner_label')))
    need('conversation id', hex_id is not None, hex_id)
    want_mounts = declared_container_mounts(profile, hex_id or '?')
    need('mounts (exactly the declared list)', effective_container_mounts(container) == want_mounts,
         effective_container_mounts(container))
    forbidden = forbidden_mount_sources(profile, container)
    need('mount sources (declared root, no forbidden path)', not forbidden, forbidden)
    need('user', config.get('User') == f"{user.get('uid')}:{user.get('gid')}" and
         user.get('name') == (server.get('user') or {}).get('name'), config.get('User'))
    need('capabilities', host.get('CapDrop') == conv.get('cap_drop') and not host.get('CapAdd'),
         {'CapDrop': host.get('CapDrop'), 'CapAdd': host.get('CapAdd')})
    need('security options', all(o in (host.get('SecurityOpt') or []) for o in
                                 conv.get('security_opt') or ['?']), host.get('SecurityOpt'))
    need('no privilege or host namespace',
         host.get('Privileged') is False and not host.get('Devices') and
         'host' not in (host.get('PidMode'), host.get('IpcMode'), host.get('NetworkMode'),
                        host.get('UsernsMode'), host.get('UTSMode')) and
         host.get('Runtime') == ((profile.get('provisioning') or {}).get('moby') or {}).get(
             'default_runtime'),
         {k: host.get(k) for k in ('Privileged', 'Devices', 'PidMode', 'IpcMode', 'NetworkMode',
                                   'UsernsMode', 'UTSMode', 'Runtime')})
    published = conv.get('published') or {}
    port_key = published.get('container_port')
    need('port binding (127.0.0.1 only)', host.get('PortBindings') == {
        port_key: [{'HostIp': published.get('host_ip'), 'HostPort': ''}]} and
        not host.get('PublishAllPorts'), host.get('PortBindings'))
    ports = ((container.get('NetworkSettings') or {}).get('Ports') or {})
    bound = ports.get(port_key) or []
    if state.get('Running'):
        need('published port', len(bound) == 1 and bound[0].get('HostIp') == published.get('host_ip')
             and str(bound[0].get('HostPort', '')).isdigit() and
             not [k for k, v in ports.items() if k != port_key and v], ports)
    need('caps (decision 0001 s3)', host.get('Memory') == memory_bytes(cfg.get(
        'conversation_container_memory')) and host.get('NanoCpus') == int(round(
            float(cfg.get('conversation_container_cpus') or 0) * 1e9)) and
        host.get('PidsLimit') == cfg.get('conversation_container_pids_limit'),
        {k: host.get(k) for k in ('Memory', 'NanoCpus', 'PidsLimit')})
    problems.extend(job_problems(profile, container))
    deviations = []
    extra = [h for h in host.get('ExtraHosts') or [] if 'host-gateway' in str(h)]
    if extra:
        deviations.append({'id': 'host-gateway', 'observed': extra})
    if host.get('NetworkMode') != 'none':
        deviations.append({'id': 'no-network-none', 'observed': host.get('NetworkMode'),
                           'networks': sorted(((container.get('NetworkSettings') or {})
                                               .get('Networks') or {}))})
    return problems, deviations


def jobs_config(profile):
    return (((profile.get('provisioning') or {}).get('agent_server') or {}).get('jobs')) or {}


def _empty(value):
    return value in (None, [], {}, '')


def job_problems(profile, container):
    """One conversation container against provisioning.agent_server.jobs (S-01.3.2): the
    declared HostConfig values and AppArmor profile (null matches an empty value), and no
    engine or credential variable in Config.Env but the conversation's own keys (names
    only). An empty list when the profile declares no job environment."""
    jobs = jobs_config(profile)
    if not jobs:
        return []
    host = container.get('HostConfig') or {}
    problems = []
    for key, want in (jobs.get('host_config') or {}).items():
        if key == 'rule':
            continue
        have = container.get(key) if key == 'AppArmorProfile' else host.get(key)
        if not (have == want or (_empty(want) and _empty(have))):
            problems.append({'check': f'job environment {key} (S-01.3.2)', 'observed': have})
    env = jobs.get('environment') or {}
    pattern = re.compile(env.get('credential_name_pattern') or '$^', re.I)
    names = (container.get('Config') or {}).get('EnvNames') or []
    bad = sorted(n for n in names if pattern.search(str(n)) and
                 n not in (env.get('secret_names') or []))
    if bad or not isinstance(names, list) or not names:
        problems.append({'check': 'job environment variables (S-01.3.2): no engine or '
                                  'credential name but the conversation keys', 'observed': bad})
    return problems


def _proxy_target(argv):
    """docker-proxy's '-container-ip X -container-port Y -host-ip A -host-port B' as a dict."""
    out = {}
    for flag, value in zip(argv or [], (argv or [])[1:]):
        if flag in ('-proto', '-host-ip', '-host-port', '-container-ip', '-container-port'):
            out[flag.lstrip('-')] = value
    return out


def listener_allowance(profile, report):
    """profiles P7 (amended 2026-11-07, F-04.2) on one root report: every TCP listener of Moby
    (dockerd, containerd, docker-proxy, containerd-shim) must be a docker-proxy or dockerd
    listener on 127.0.0.1 at a port inside ip_local_port_range, mapped to the port 8000 of
    exactly one running conversation container that the Agent Server owns, at most one per
    container. Returns {'allowed': [...], 'violations': [...]}."""
    conv = conversations_config(profile.get('provisioning'))
    published = conv.get('published') or {}
    port_key = published.get('container_port', '8000/tcp')
    containers = [c for c in report.get('containers') or [] if isinstance(c, dict)]
    owner = conversation_owner(profile)
    running = [c for c in containers if (c.get('State') or {}).get('Running') and
               ((c.get('Config') or {}).get('Labels') or {}).get(conv.get('owner_label')) == owner]
    try:
        low, high = (int(x) for x in report.get('ip_local_port_range') or [])
    except (TypeError, ValueError):
        low, high = None, None
    proxies = {(p.get('local'), p.get('process')): p for p in report.get('proxies') or []
               if isinstance(p, dict)}
    allowed, violations, used = [], [], set()
    lines = report.get('tcp_listeners') if isinstance(report.get('tcp_listeners'), list) else []
    for line in lines:
        process = _listener_process(line)
        if process not in MOBY_PROCESSES:
            continue
        local = line.split()[3] if len(line.split()) > 3 else ''
        address, _, port = local.rpartition(':')
        target = _proxy_target((proxies.get((local, process)) or {}).get('argv'))
        matches = [c for c in running if any(
            b.get('HostIp') == published.get('host_ip') and str(b.get('HostPort')) == port
            for b in (((c.get('NetworkSettings') or {}).get('Ports') or {}).get(port_key) or []))]
        if process == 'docker-proxy':
            ips = {(n or {}).get('IPAddress') for c in matches for n in
                   ((c.get('NetworkSettings') or {}).get('Networks') or {}).values()}
            mapped = target.get('container-ip') in ips and \
                f"{target.get('container-port')}/{target.get('proto', 'tcp')}" == port_key and \
                target.get('host-ip') == published.get('host_ip') and target.get('host-port') == port
        else:
            mapped = True
        reasons = []
        if process not in ('docker-proxy', 'dockerd'):
            reasons.append(f'{process} may not listen')
        if address != published.get('host_ip'):
            reasons.append('not on 127.0.0.1')
        if not (port.isdigit() and low is not None and low <= int(port) <= high):
            reasons.append('port outside ip_local_port_range')
        if len(matches) != 1:
            reasons.append(f'maps to {len(matches)} running owned containers')
        elif not mapped:
            reasons.append(f'docker-proxy forwards to {target}, not to the container port')
        elif matches[0].get('Id') in used:
            reasons.append('a second listener for one container')
        if reasons:
            violations.append({'line': line, 'reasons': reasons})
        else:
            used.add(matches[0].get('Id'))
            allowed.append({'process': process, 'local': local,
                            'container': str(matches[0].get('Id'))[:12],
                            'target': f"{target.get('container-ip')}:{target.get('container-port')}"
                            if target else None})
    return {'allowed': allowed, 'violations': violations,
            'running_owned': [str(c.get('Id'))[:12] for c in running]}


def conversation_containers_view(profile, record, report):
    """Every container in the report against the declared shape: problems, deviations, and
    whether every container in Moby's store is an owned one."""
    conv = conversations_config(profile.get('provisioning'))
    containers = report.get('containers')
    if not isinstance(containers, list):
        return {'error': containers}, False
    owner = conversation_owner(profile)
    out, ok = [], True
    for c in containers:
        problems, deviations = container_problems(profile, record, report, c)
        ok = ok and not problems
        out.append({'id': c.get('Id'), 'name': c.get('Name'),
                    'conversation': conversation_hex(c), 'running': (c.get('State') or {}).get('Running'),
                    'image': c.get('Image'), 'user': (c.get('Config') or {}).get('User'),
                    'mounts': [list(m) for m in effective_container_mounts(c)],
                    'ports': ((c.get('NetworkSettings') or {}).get('Ports')),
                    'problems': problems, 'deviations': deviations})
    labels_ok = all(((c.get('Config') or {}).get('Labels') or {}).get(conv.get('owner_label')) == owner
                    for c in containers)
    only_owned = report.get('containers_all_count') == len(containers)
    return {'count': len(containers), 'containers': out, 'owner': owner,
            'containers_all_count': report.get('containers_all_count')}, \
        ok and labels_ok and only_owned


def secret_fingerprint(value):
    """The fingerprint the root step publishes for a guest-local secret (never the value)."""
    data = value if isinstance(value, bytes) else str(value).encode('ascii')
    return hashlib.sha256(b'aieh-secret-fingerprint/v1\n' + data).hexdigest()


SECRET_TOKEN = re.compile(rb'[A-Za-z0-9_-]{43,}')
SECRET_WINDOW = 43
SECRET_SCAN_SKIP = ('root.qcow2', 'scratch.qcow2')     # the guest's own disks hold them


def scan_secret_bytes(data, session_key, secret_fp):
    """Occurrences of the session key (a literal) and of the secret whose fingerprint is
    secret_fp (every 43-character window of every token run is fingerprinted) in data."""
    hits = {'OH_SESSION_API_KEYS_0': data.count(session_key) if session_key else None,
            'OH_SECRET_KEY': None}
    if secret_fp:
        found = 0
        for match in SECRET_TOKEN.finditer(data):
            run = match.group()
            for i in range(len(run) - SECRET_WINDOW + 1):
                if secret_fingerprint(run[i:i + SECRET_WINDOW]) == secret_fp:
                    found += 1
        hits['OH_SECRET_KEY'] = found
    return hits


def agent_server_secret_scan(idir, session_key, secret_fp, extra=None):
    """Host-side search of the instance directory (every file but the guest disks; the
    session key's own custody file only for OH_SECRET_KEY) and of ``extra`` byte strings
    for the two Agent Server secrets. Returns counts, never a value."""
    idir = Path(idir)
    custody = idir / 'agent-server' / 'session.key'
    hits, scanned = {}, 0
    for path in sorted(idir.rglob('*')):
        if not path.is_file() or path.name in SECRET_SCAN_SKIP:
            continue
        scanned += 1
        found = scan_secret_bytes(path.read_bytes(), session_key, secret_fp)
        if path == custody:
            found['OH_SESSION_API_KEYS_0'] = None
        found = {k: v for k, v in found.items() if v}
        if found:
            hits[posix(path.relative_to(idir))] = found
    for label, data in (extra or {}).items():
        scanned += 1
        found = {k: v for k, v in scan_secret_bytes(data, session_key, secret_fp).items() if v}
        if found:
            hits[label] = found
    return {'files_scanned': scanned, 'hits': hits,
            'searched': {'OH_SESSION_API_KEYS_0': session_key is not None,
                         'OH_SECRET_KEY': secret_fp is not None}}


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
            int(str(s.get('mode', '7')), 8) & 0o002)]
    connect = dict(line.rsplit(' ', 1) for line in out_text('moby_agent_connect').splitlines()
                   if ' ' in line)
    cli = g.get('docker_as_agent') or {}
    return [
        check('guest Moby sockets', {'declared': declared, 'others': 'root-owned, group root '
                                     'or docker, not writable by others (no connect)'},
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


def moby_p7_checks(obs, profile=None, record=None):
    """profiles P7 for a provisioned instance: no TCP listener of Moby at boot (unix socket
    only); now, only the amended allowance (F-04.2): one docker-proxy or dockerd listener on
    127.0.0.1 at an ephemeral port per running conversation container of the Agent Server,
    mapped to its port 8000; agent sees the same listeners as root. The inference endpoint's
    sshd listener while a forward session is recorded (decision 0015) is judged by its own
    check and left out of both views, so the record compares across a start."""
    g = obs.get('guest', {})
    facts = _probe_json(obs, 'moby_facts') or {}
    root_lines = facts.get('tcp_listeners') if isinstance(facts.get('tcp_listeners'), list) else None
    moby_owned = None if root_lines is None else [
        line for line in root_lines if any(f'(("{p}' in line or f'"{p}"' in line
                                           for p in MOBY_PROCESSES)]
    report = conversation_report(obs)
    now_lines = (report or {}).get('tcp_listeners')
    now_lines = now_lines if isinstance(now_lines, list) else None
    allowance = listener_allowance(profile or {}, report) if now_lines is not None else None
    forward = obs.get('inference_forward') if isinstance(obs.get('inference_forward'), dict) else {}
    held = {line.split()[3] for line in inference_listener_lines(
        profile or {}, record or {}, report, forward.get('recorded') is True)[0]}
    agent_view = [a for a in _listener_addresses((g.get('tcp_listeners') or {}).get('out', '')
                                                 .splitlines()) if a not in held]
    root_view = None if now_lines is None else [a for a in _listener_addresses(now_lines)
                                                if a not in held]
    return [check('guest TCP listeners (Moby)',
                  {'boot': 'none owned by dockerd, containerd or docker-proxy',
                   'now': 'only the P7 allowance: one docker-proxy or dockerd listener on '
                          '127.0.0.1 at an ephemeral port per running conversation container '
                          'of the Agent Server, mapped to its port 8000',
                   'agent_view': 'equal to the root view'},
                  {'agent_view': agent_view, 'root_view': root_view,
                   'boot_moby_owned': moby_owned, 'allowance': allowance},
                  'guest: ss -ltnH (agent, now); ss -ltnpH and docker-proxy argv in the on-demand '
                  'conversation facts (root, now); ss -ltnpH in the boot facts report (root)',
                  None if root_lines is None or allowance is None else
                  not moby_owned and agent_view == root_view and not allowance['violations'])]


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


def tar_secret_scan(tar_bytes, session_key, secret_fp):
    """scan_secret_bytes over every regular member of the P5 collection (as agent)."""
    totals = {'OH_SESSION_API_KEYS_0': 0 if session_key else None,
              'OH_SECRET_KEY': 0 if secret_fp else None}
    members = 0
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode='r:*') as tf:
        for member in tf:
            if not member.isfile() or member.size > MEMBER_MAX_BYTES:
                continue
            handle = tf.extractfile(member)
            if handle is None:
                continue
            members += 1
            for key, count in scan_secret_bytes(handle.read(), session_key, secret_fp).items():
                if count:
                    totals[key] += count
    return {'members': members, 'hits': {k: v for k, v in totals.items() if v}}


# Listeners of the base guest image (sshd, systemd-resolved); every other TCP listener of a
# provisioned guest must be declared (profiles P7: the Agent Server's guest-local bind).
BASE_LISTENER_PROCESSES = ('sshd', 'systemd-resolve')
AGENT_SERVER_ENGINE_WARNINGS = ('Failed to list stale conversation containers',
                                'Docker CLI not found')
AGENT_SERVER_UNIT_SETS = ('IPAddressAllow', 'IPAddressDeny', 'RestrictAddressFamilies',
                          'ReadWritePaths', 'CapabilityBoundingSet', 'AmbientCapabilities')


def _listener_process(line):
    match = re.search(r'users:\(\("([^"]+)"', line)
    return match.group(1) if match else None


def agent_server_checks(profile, record, obs):
    """The Agent Server of a provisioned instance (F-04.1 slice (c)) against the profile's
    provisioning.agent_server, decision 0001 s2 and the lock: {'P5': [...], 'P7': [...],
    'provisioning': [...]}. Root-only facts come from the boot-time report."""
    g = obs.get('guest', {})
    out_text = lambda key: (g.get(key) or {}).get('out', '')      # noqa: E731
    conf = (profile.get('provisioning') or {}).get('agent_server') or {}
    prov = record.get('provisioning') or {}
    facts = _probe_json(obs, 'moby_facts') or {}
    server = facts.get('agent_server') if isinstance(facts.get('agent_server'), dict) else {}
    api = _probe_json(obs, 'agent_server_api') or {}
    info = ((api.get('server_info') or {}).get('body')) if isinstance(api.get('server_info'), dict) else None
    info = info if isinstance(info, dict) else {}
    sec = server.get('secrets') if isinstance(server.get('secrets'), dict) else {}
    fps = sec.get('fingerprints') if isinstance(sec.get('fingerprints'), dict) else {}
    secrets_conf, key_conf = conf.get('secrets') or {}, conf.get('session_key') or {}
    listener = conf.get('listener') or {}
    want_bind = f"{listener.get('address')}:{listener.get('port')}"
    files = {line.split('|', 1)[0]: line.split('|')[1:] for line in
             out_text('agent_server_files').splitlines() if '|' in line}
    key_dir = str(key_conf.get('guest_path', '')).rsplit('/', 1)[0]
    want_files = {
        conf.get('binary', {}).get('path'): [conf.get('binary', {}).get('owner'),
                                             conf.get('binary', {}).get('group'),
                                             conf.get('binary', {}).get('mode'), 'regular file'],
        conf.get('config', {}).get('path'): [conf.get('config', {}).get('owner'),
                                             conf.get('config', {}).get('group'),
                                             conf.get('config', {}).get('mode'), 'regular file'],
        secrets_conf.get('env_file'): [secrets_conf.get('owner'), secrets_conf.get('group'),
                                       secrets_conf.get('mode'), 'regular file'],
        key_dir: [key_conf.get('guest_dir_owner'), key_conf.get('guest_dir_group'),
                  key_conf.get('guest_dir_mode'), 'directory'],
        key_conf.get('guest_path'): [key_conf.get('owner'), key_conf.get('group'),
                                     key_conf.get('mode'), 'regular file'],
    }
    agent_open = api.get('agent_open') if isinstance(api.get('agent_open'), dict) else {}
    custody = obs.get('agent_server_custody') or {}
    host_fp = custody.get('host_fingerprint')
    scan = obs.get('agent_server_secrets') or {}
    occurrences = sec.get('occurrences') if isinstance(sec.get('occurrences'), dict) else None
    journal = server.get('journal') if isinstance(server.get('journal'), dict) else {}
    guest_counts = None if occurrences is None else {
        'files': {k: {n: c for n, c in v.items() if c} for k, v in occurrences.items()
                  if any((v or {}).values())},
        'start-up log': {n: c for n, c in (journal.get('secret_occurrences') or {}).items() if c},
        'facts report': {n: c for n, c in (facts.get('secret_occurrences_in_report') or {}).items()
                         if c}}
    p5 = [
        check('Agent Server secrets (custody)', {
            'files': want_files, 'agent_open': {secrets_conf.get('env_file'): 'EACCES',
                                                key_conf.get('guest_path'): 'READABLE'},
            'server_environment_as_agent': ['EACCES'],
            'values': 'two distinct 43-character values; the session key file holds the key',
            'host_copy': f"{key_conf.get('host_path')} equals the guest's session key (fingerprint)"},
            {'files': files, 'agent_open': agent_open,
             'server_environment_as_agent': api.get('server_environ_agent'),
             'values_valid': sec.get('values_valid'),
             'session_key_matches': sec.get('session_key_matches'),
             'host_copy': {'present': custody.get('present'),
                           'equal': bool(host_fp) and host_fp == fps.get('OH_SESSION_API_KEYS_0')
                           and host_fp == api.get('session_key_fingerprint')}},
            "guest, as agent: stat; open() of the secret files and /proc/<openhands pid>/environ "
            "(nothing read); facts (root): values and the session key file; host: the "
            "custody file's fingerprint",
            bool(files) and files == want_files and
            agent_open.get(secrets_conf.get('env_file')) == 'EACCES' and
            agent_open.get(key_conf.get('guest_path')) == 'READABLE' and
            api.get('server_environ_agent') == ['EACCES'] and sec.get('values_valid') is True and
            sec.get('session_key_matches') is True and bool(host_fp) and
            host_fp == fps.get('OH_SESSION_API_KEYS_0') == api.get('session_key_fingerprint')),
        check('Agent Server secret values in records', {'host': {}, 'p5_collection': {},
                                                         'guest': 'no occurrence'},
              {'host': {'files_scanned': (scan.get('host') or {}).get('files_scanned'),
                        'hits': (scan.get('host') or {}).get('hits'),
                        'searched': (scan.get('host') or {}).get('searched')},
               'p5_collection': scan.get('p5_collection'), 'guest': guest_counts},
              'host: the session key and every 43-character window fingerprinted against '
              "OH_SECRET_KEY's, over the instance directory (not the guest disks), this "
              "inspect's observations and the P5 collection; guest (root): RESULT.json, the "
              'config, the manifest, cloud-init logs, the start-up log and the facts report',
              bool(scan) and (scan.get('host') or {}).get('hits') == {} and
              all((scan.get('host') or {}).get('searched', {}).values()) and
              isinstance(scan.get('p5_collection'), dict) and
              scan['p5_collection'].get('hits') == {} and guest_counts is not None and
              not any(guest_counts.values())),
        check('Agent Server key fingerprints', 'per instance',
              {k: fps.get(k) for k in secrets_conf.get('variables') or []},
              'facts (root): sha256 of the domain prefix and the value', len(fps) == 2 and
              all(isinstance(v, str) and len(v) == 64 for v in fps.values())),
    ]

    # root's listeners now (the on-demand conversation facts); a Moby listener inside the
    # P7 allowance (F-04.2) is declared, every other one beyond the base image's is not
    report = conversation_report(obs)
    root_lines = (report or {}).get('tcp_listeners')
    root_lines = root_lines if isinstance(root_lines, list) else None
    allowed = {a['local'] for a in (listener_allowance(profile, report)['allowed']
                                    if root_lines is not None else [])}
    # decision 0015: the inference endpoint's sshd listener while a forward session is
    # recorded (its own check judges it)
    inference_lines = set(inference_listener_lines(
        profile, record, report,
        (obs.get('inference_forward') or {}).get('recorded') is True)[0])
    by_process = {}
    for line in root_lines or []:
        if (line.split()[3] if len(line.split()) > 3 else None) in allowed or \
                line in inference_lines:
            continue
        by_process.setdefault(_listener_process(line), []).extend(_listener_addresses([line]))
    agent_view = _listener_addresses((g.get('tcp_listeners') or {}).get('out', '').splitlines())
    undeclared = {p: a for p, a in by_process.items()
                  if p not in BASE_LISTENER_PROCESSES + (listener.get('process'),)}
    p7 = [check('guest TCP listeners (Agent Server)',
                {'agent-server': [want_bind], 'others': f'only {list(BASE_LISTENER_PROCESSES)} '
                 'and the P7 allowance for conversation containers'},
                {'agent-server': sorted(set(by_process.get(listener.get('process'), []))),
                 'undeclared': undeclared, 'seen_by_agent': want_bind in agent_view},
                'on-demand conversation facts: ss -ltnpH (root, now); guest: ss -ltnH (agent)',
                None if root_lines is None else
                sorted(set(by_process.get(listener.get('process'), []))) == [want_bind] and
                not undeclared and want_bind in agent_view)]

    unit = server.get('unit') if isinstance(server.get('unit'), dict) else {}
    account = server.get('account') if isinstance(server.get('account'), dict) else {}
    procs = server.get('processes') if isinstance(server.get('processes'), list) else []
    user = conf.get('user') or {}
    config_want = (conf.get('config') or {}).get('content')
    try:
        config_seen = json.loads(out_text('agent_server_config'))
    except ValueError:
        config_seen = None
    paths = server.get('paths') if isinstance(server.get('paths'), list) else []
    dirs = agent_server_directories(profile)
    want_paths = [{'path': d['path'], 'state': 'directory', 'owner': d['owner'],
                   'group': d['group'], 'mode': d['mode'], 'mount': ['/srv/scratch', 'ext4']}
                  for d in dirs]
    env = conf.get('environment') or {}
    config_paths = {k: (config_want or {}).get(k) for k in (
        'conversations_path', 'workspace_path', 'bash_events_dir', 'conversation_worktree_root')}
    config_paths.update({k: env.get(k) for k in ('OH_PERSISTENCE_DIR', 'HOME', 'TMPDIR')})
    declared_dirs = {d['path'] for d in dirs}
    engine = server.get('engine') if isinstance(server.get('engine'), dict) else {}
    docker_env = sorted({json.dumps(p.get('docker_environment'), sort_keys=True) for p in procs})
    engine_warnings = [line for line in (journal.get('head') or []) + (journal.get('noted') or [])
                       if any(w in line for w in AGENT_SERVER_ENGINE_WARNINGS)]
    moby = (profile.get('provisioning') or {}).get('moby') or {}
    caps = ('conversation_runtime_routes_v1', 'idempotent_conversation_create_v1')
    runtime_ok = (info.get('conversation_runtime') == 'docker' or
                  'docker' in (info.get('available_conversation_runtimes') or [])) and \
        all(c in (info.get('capabilities') or []) for c in caps)
    statuses = {k: (api.get(k) or {}).get('status') for k in
                ('count_with_key', 'count_without_key', 'count_wrong_key', 'alive')}
    image = facts.get('image') if isinstance(facts.get('image'), dict) else {}
    hardening = (conf.get('service') or {}).get('hardening', {}).get('options') or []
    unit_view = {k: unit.get(k) for k in ('LoadState', 'ActiveState', 'SubState', 'UnitFileState',
                                          'NRestarts', 'User', 'Group', 'NoNewPrivileges',
                                          'ProtectSystem', 'ProtectHome', 'PrivateTmp',
                                          'PrivateDevices', 'ProtectProc', 'RestrictNamespaces',
                                          'RestrictSUIDSGID', 'CapabilityBoundingSet',
                                          'AmbientCapabilities', 'IPAddressDeny', 'IPAddressAllow',
                                          'RestrictAddressFamilies', 'SystemCallArchitectures',
                                          'UMask', 'ReadWritePaths')}
    # systemctl show prints these sets in no fixed order (observed in F-04.1c across
    # recreate: '127.0.0.0/8 ::1/128' then '::1/128 127.0.0.0/8')
    for key in AGENT_SERVER_UNIT_SETS:
        if isinstance(unit_view.get(key), str):
            unit_view[key] = ' '.join(sorted(unit_view[key].split()))
    proc_view = sorted({json.dumps({k: p.get(k) for k in ('name', 'user', 'group', 'groups', 'exe',
                                                           'error')}, sort_keys=True)
                        for p in procs})
    service_ok = (unit.get('ActiveState') == 'active' and unit.get('UnitFileState') == 'enabled' and
                  unit.get('NRestarts') == '0' and unit.get('User') == user.get('name') and
                  unit.get('NoNewPrivileges') == 'yes' and unit.get('ProtectSystem') == 'strict' and
                  unit.get('ProtectProc') == 'invisible' and
                  unit.get('CapabilityBoundingSet') == '' and
                  unit.get('IPAddressDeny') and unit.get('IPAddressAllow') and
                  account.get('shell') == user.get('shell') and account.get('password') == 'L' and
                  sorted(account.get('groups') or []) == sorted([user.get('name')] +
                                                                (user.get('groups') or [])) and
                  bool(procs) and all(p.get('user') == user.get('name') and
                                      'docker' in (p.get('groups') or []) and
                                      p.get('exe') == conf.get('binary', {}).get('path')
                                      for p in procs))
    provisioning = [
        check('Agent Server binary', {'sha256': prov.get('agent_server', {}).get('binary_sha256'),
                                      'path': conf.get('binary', {}).get('path'),
                                      'owner': 'root:root', 'mode': conf.get('binary', {}).get('mode')},
              server.get('binary'), 'facts: sha256 and stat (root)',
              bool(server.get('binary')) and
              server['binary'].get('sha256') == prov.get('agent_server', {}).get('binary_sha256') and
              server['binary'].get('owner') == 'root' and server['binary'].get('group') == 'root' and
              server['binary'].get('mode') == conf.get('binary', {}).get('mode')),
        check('Agent Server version (/server_info)', {'version': conf.get('version')},
              {k: info.get(k) for k in ('title', 'version', 'sdk_version', 'tools_version',
                                        'workspace_version', 'build_git_sha', 'build_git_ref')},
              'guest, as agent: GET /server_info on the loopback listener',
              info.get('version') == conf.get('version')),
        check('runtime selection (decision 0001 s2)', {
            'conversation_runtime': 'docker', 'available_conversation_runtimes': [],
            'capabilities': f'including {list(caps)}',
            'condition': "(conversation_runtime == 'docker' or 'docker' in "
                         "available_conversation_runtimes) and both capabilities"},
              {'conversation_runtime': info.get('conversation_runtime'),
               'available_conversation_runtimes': info.get('available_conversation_runtimes'),
               'capabilities': info.get('capabilities')},
              'guest, as agent: GET /server_info',
              runtime_ok and info.get('conversation_runtime') == 'docker' and
              info.get('available_conversation_runtimes') == []),
        check('Agent Server service', {
            'unit': 'enabled, active, no restart, as the declared user, hardened',
            'hardening': hardening, 'user': user,
            'processes': f"as {user.get('name')} with group docker, exe {conf.get('binary', {}).get('path')}"},
              {'unit': unit_view, 'account': account, 'processes': proc_view,
               'enabled': server.get('enabled')},
              'facts: systemctl show, getent/id/passwd -S, /proc/<pid>/status and exe (root)',
              bool(service_ok)),
        check('Agent Server config', config_want, config_seen,
              f"guest, as agent: cat {conf.get('config', {}).get('path')}",
              config_seen is not None and config_seen == config_want and
              (server.get('config') or {}).get('content') == config_want),
        check('engine endpoint', {'docker_context_host': 'unix:///var/run/docker.sock',
                                  'server_environment': 'no DOCKER_* variable',
                                  'docker_server_version_as_openhands': moby.get('server_version'),
                                  'start-up log': f'none of {list(AGENT_SERVER_ENGINE_WARNINGS)}'},
              {'docker_context_host': engine.get('docker_context_host'),
               'server_environment': docker_env,
               'docker_server_version_as_openhands': engine.get('docker_server_version_as_openhands'),
               'start-up log': engine_warnings},
              'facts (root): docker context inspect and docker version as openhands (setpriv), '
              'DOCKER_* of the server processes, the start-up log',
              engine.get('docker_context_host') == 'unix:///var/run/docker.sock' and
              docker_env == ['{}'] and
              engine.get('docker_server_version_as_openhands') == moby.get('server_version') and
              not engine_warnings),
        check('conversation image', {'conversation_image': prov.get('local_tag'),
                                     'Id': prov.get('image_id')},
              {'conversation_image': (config_seen or {}).get('conversation_image'),
               'Id': image.get('Id'), 'RepoTags': image.get('RepoTags')},
              'config (agent); facts: docker image inspect of the tag (root, offline)',
              (config_seen or {}).get('conversation_image') == prov.get('local_tag') and
              image.get('Id') == prov.get('image_id') and
              image.get('RepoTags') == [prov.get('local_tag')]),
        check('Agent Server data paths', {'directories': want_paths, 'configured': config_paths},
              {'directories': paths, 'configured_declared': {
                  k: v in declared_dirs for k, v in config_paths.items()}},
              'facts: stat and findmnt --target (root); config and unit environment',
              paths == want_paths and all(v in declared_dirs for v in config_paths.values())),
        check('session API key enforced', {'count_with_key': 200, 'count_without_key': 401,
                                           'count_wrong_key': 401, 'alive': 200},
              statuses, 'guest, as agent: GET /api/conversations/count and /alive',
              statuses == {'count_with_key': 200, 'count_without_key': 401,
                           'count_wrong_key': 401, 'alive': 200}),
        check('Agent Server start-up log', 'recorded; secret values counted and redacted (none)',
              {'lines': journal.get('lines'), 'secret_occurrences': journal.get('secret_occurrences'),
               'head': journal.get('head'), 'noted': journal.get('noted')},
              'facts: journalctl -b -u (root), redacted before it is written',
              bool(journal) and journal.get('rc') == 0 and
              not any((journal.get('secret_occurrences') or {}).values())),
    ]
    conv = conf.get('conversations') or {}
    cfacts = conv.get('facts') or {}
    raw = _probe_json(obs, 'conversation_facts')
    request = (report or {}).get('request') or {}
    units = (report or {}).get('units') or {}
    provisioning.append(check(
        'on-demand conversation facts',
        {'report': cfacts.get('report'), 'schema': CONVERSATION_FACTS_SCHEMA,
         'boot': 'this boot', 'request': 'consumed (removed, never read)',
         'units': {cfacts.get('path_unit'): 'enabled', cfacts.get('service'): 'static'}},
        {'serial': report.get('serial'),
         'same_boot': report.get('boot_id') == out_text('boot_id').strip(),
         'request': request, 'units': units, 'seconds': report.get('seconds'),
         'secret_values_redacted': report.get('secret_values_redacted'),
         'secret_occurrences_in_report': report.get('secret_occurrences_in_report')}
        if report else {'probe': raw if raw is not None else out_text('conversation_facts')[-500:]},
        "guest, as agent: create the request file, wait (inotify) for the root reporter's "
        'report of a run started after the request',
        None if report is None else
        report.get('boot_id') == out_text('boot_id').strip() and request.get('consumed') is True
        and units.get(cfacts.get('path_unit')) == 'enabled'))
    view, view_ok = conversation_containers_view(profile, record, report) if report \
        else (None, None)
    provisioning.append(check(
        'conversation containers',
        {'shape': 'provisioning.agent_server.conversations: the locked image ID, the declared '
                  'mounts exactly, the service user, cap-drop ALL, no-new-privileges, 127.0.0.1 '
                  'port binding only, the config caps, the owner label',
         'store': 'every container in Moby carries the owner label',
         'deviations': 'recorded, not failed: ' + ', '.join(
             d.get('id', '') for d in conv.get('deviations') or [])},
        view, 'on-demand conversation facts: docker ps --filter label and docker container '
              'inspect (root)', view_ok))
    return {'P5': p5, 'P7': p7, 'provisioning': provisioning}


def provisioning_property(profile, record, obs, extra=()):
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
    host_config = facts.get('host_config') if isinstance(facts.get('host_config'), dict) else {}
    ipv6 = facts.get('ipv6') if isinstance(facts.get('ipv6'), dict) else {}
    want_daemon = declared_daemon_json(profile, inference_opted(record))
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
                              'daemon.json': want_daemon,
                              'containerd config.toml': (moby.get('containerd_config') or {}).get('content'),
                              'sysctl drop-in': (moby.get('sysctl') or {}).get('content'),
                              'docker0 disable_ipv6': '1'},
              {'DockerRootDir': info.get('DockerRootDir'), 'Driver': info.get('Driver'),
               'DefaultRuntime': info.get('DefaultRuntime'), 'SecurityOptions': security,
               'daemon.json': facts.get('daemon_json'),
               'containerd config.toml': host_config.get('containerd_config'),
               'sysctl drop-in': host_config.get('sysctl'),
               'docker0 disable_ipv6': ipv6.get('docker0_disable_ipv6')},
              'facts: docker info, daemon.json, containerd config.toml, the sysctl drop-in, '
              'docker0 disable_ipv6 (root)',
              bool(info) and info.get('DockerRootDir') == moby.get('data_root') and
              info.get('Driver') == moby.get('storage_driver') and
              info.get('DefaultRuntime') == moby.get('default_runtime') and
              set(moby.get('required_security_options') or []) <= set(security) and
              facts.get('daemon_json') == want_daemon and
              host_config.get('containerd_config') == (moby.get('containerd_config') or {}).get(
                  'content') and
              host_config.get('sysctl') == (moby.get('sysctl') or {}).get('content') and
              ipv6.get('docker0_disable_ipv6') == '1'),
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
    checks += list(extra)
    out = prop('provisioning', checks, formal='F-04.1 slices (b) and (c)', note=(
        'Not a contract property: the provisioned instance\'s Moby, image and Agent Server '
        'state against the profile\'s provisioning block, decision 0001 s2 and the provision '
        'lock. Root-only facts come from the boot-time report of aieh-docker-facts.service, '
        'read as agent; the Agent Server API is queried as agent on the guest loopback.'))
    out['property'] = PROVISIONING_PROPERTY
    return out


def _n_moby_sockets(value, profile):
    if not isinstance(value, dict):
        return value
    out = dict(value)
    for key in ('root_view', 'open_to_others'):
        if isinstance(out.get(key), list):
            out[key] = sorted({json.dumps(dict(s, path=MOBY_VOLATILE_SOCKET.sub(r'\1*\2', str(
                s.get('path')))), sort_keys=True) for s in out[key] if isinstance(s, dict)})
    return out


MOBY_VOLATILE_SOCKET = re.compile(r'^(/run/docker/libnetwork/)[0-9a-f]+(\.sock)$')
NORMALIZERS['moby-sockets'] = _n_moby_sockets

CHECK_CLASSES.update({
    # libnetwork names its per-daemon socket with a random id at every start
    ('profiles P6', 'guest Moby sockets'): (STABLE, 'moby-sockets'),
    ('profiles P6', 'agent cannot reach Moby'): (STABLE, None),
    ('profiles P7', 'guest TCP listeners (Moby)'): (STABLE, None),
    ('profiles P8', 'agent not in group docker'): (STABLE, None),
    (PROVISIONING_PROPERTY, 'root step result'): (STABLE, None),
    (PROVISIONING_PROPERTY, 'facts report of this boot'): (STABLE, None),
    (PROVISIONING_PROPERTY, 'Moby server version'): (STABLE, None),
    (PROVISIONING_PROPERTY, 'Moby daemon'): (STABLE, None),
    (PROVISIONING_PROPERTY, 'image'): (STABLE, None),
    (PROVISIONING_PROPERTY, 'containers'): (STABLE, None),
    # the loaded set depends on what ran since boot (veth after a container); the verdict
    # (overlay loaded) must stay equal
    (PROVISIONING_PROPERTY, 'kernel modules for Moby'): (VOLATILE, None),
    (PROVISIONING_PROPERTY, 'upload and staging removed'): (STABLE, None),
    (PROVISIONING_PROPERTY, 'root step disabled'): (STABLE, None),
    # F-04.1 slice (c): the Agent Server
    ('profiles P5', 'Agent Server secrets (custody)'): (STABLE, None),
    # the instance directory gains records between inspects: only the hits are compared
    ('profiles P5', 'Agent Server secret values in records'): (STABLE, 'secret-scan'),
    # generated per instance: equal across a restart, different across recreate
    ('profiles P5', 'Agent Server key fingerprints'): (PER_INSTANCE, None),
    ('profiles P7', 'guest TCP listeners (Agent Server)'): (STABLE, None),
    (PROVISIONING_PROPERTY, 'Agent Server binary'): (STABLE, None),
    (PROVISIONING_PROPERTY, 'Agent Server version (/server_info)'): (STABLE, None),
    (PROVISIONING_PROPERTY, 'runtime selection (decision 0001 s2)'): (STABLE, None),
    (PROVISIONING_PROPERTY, 'Agent Server service'): (STABLE, None),
    (PROVISIONING_PROPERTY, 'Agent Server config'): (STABLE, None),
    (PROVISIONING_PROPERTY, 'engine endpoint'): (STABLE, None),
    (PROVISIONING_PROPERTY, 'conversation image'): (STABLE, None),
    (PROVISIONING_PROPERTY, 'Agent Server data paths'): (STABLE, None),
    (PROVISIONING_PROPERTY, 'session API key enforced'): (STABLE, None),
    # timestamps and process ids change with every start; the verdict (no secret value in
    # it) must stay equal
    (PROVISIONING_PROPERTY, 'Agent Server start-up log'): (VOLATILE, None),
    # F-04.2: the on-demand report's serial and timing change with every request
    (PROVISIONING_PROPERTY, 'on-demand conversation facts'): (VOLATILE, None),
    # container ids, names and published ports are allocated per run: the count, the
    # owner label and the problems and deviations found are compared
    (PROVISIONING_PROPERTY, 'conversation containers'): (STABLE, 'containers'),
})


def _n_containers(value, profile):
    if not isinstance(value, dict) or not isinstance(value.get('containers'), list):
        return value
    return {'count': value.get('count'), 'containers_all_count': value.get('containers_all_count'),
            'owner': value.get('owner'),
            'problems': sorted({p.get('check') for c in value['containers']
                                for p in c.get('problems') or []}),
            'deviations': sorted({d.get('id') for c in value['containers']
                                  for d in c.get('deviations') or []})}


NORMALIZERS['containers'] = _n_containers


def _n_secret_scan(value, profile):
    if not isinstance(value, dict):
        return value
    return {'host_hits': (value.get('host') or {}).get('hits'),
            'host_searched': (value.get('host') or {}).get('searched'),
            'p5_hits': (value.get('p5_collection') or {}).get('hits')
            if isinstance(value.get('p5_collection'), dict) else value.get('p5_collection'),
            'guest': value.get('guest')}


NORMALIZERS['secret-scan'] = _n_secret_scan


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
    manifest = build_provision_manifest(ctx, prov.get('egress_falsification') is True)
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
        'agent_server_started': ((steps.get('agent-server-start') or {}).get('detail') or {}).get(
            'agent_server_listeners') == [f"{conf['agent_server']['listener']['address']}:"
                                          f"{conf['agent_server']['listener']['port']}"],
    }
    # profiles P5 (amended 2026-11-07): the session API key is exported, by SFTP as agent,
    # into the instance directory only. Neither it nor OH_SECRET_KEY is recorded; the
    # record says only whether the copy's fingerprint equals the one the root step published.
    published = ((((steps.get('agent-server-secrets') or {}).get('detail') or {})
                  .get('fingerprints') or {}).get('OH_SESSION_API_KEYS_0'))
    custody = idir / 'agent-server' / 'session.key'
    session = {'host_path': posix(custody), 'fetched': False, 'fingerprint_matches': False}
    if verdict['provisioned'] and published and not custody.exists():
        custody.parent.mkdir(exist_ok=True)
        guest_key = conf['agent_server']['session_key']['guest_path']
        got = Sftp(ssh).batch([f'get {sftp_quote(guest_key)} {sftp_quote(custody)}'], work)
        session['fetched'] = got['rc'] == 0 and custody.is_file()
        if session['fetched']:
            session['fingerprint_matches'] = secret_fingerprint(
                custody.read_bytes().strip()) == published
    out['session_key'] = session
    verdict['session_key_exported'] = session['fingerprint_matches']
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


# ---------------------------------------------------------------- conversation lifecycle (F-04.2)
#
# The disposable Docker conversation of the profile's fixture, driven over the Agent
# Server API as agent on the guest loopback (exec channel), with the root facts of its
# container from the on-demand reporter. No LLM, no message, no repository content.

CONVERSATION_SMOKE_SCHEMA = 'ai-engineering-harness/profiles/conversation-smoke-record/v1'

# Run as agent: the requests (base64 JSON in argv) against the Agent Server on its loopback
# listener, with the session key read from its agent-readable file (never on a command
# line, never printed: any occurrence in a response is counted and redacted). Prints one
# JSON line: the responses (status, JSON body or text) and the redaction count.
API_PROBE = r'''import base64, errno, http.client, json, sys, time
key_path, host, port = sys.argv[1], sys.argv[2], int(sys.argv[3])
# sealed (decision 0015): the requests and one secret arrive in this script's own text on standard
# input (SEALED, prepended), never as an argument; the secret is redacted from every answer
spec, sealed = (sys.argv[4], None) if len(sys.argv) > 4 else SEALED
requests = json.loads(base64.b64decode(spec).decode('utf-8'))
with open(key_path, encoding='ascii') as handle:
    key = handle.read().strip()
out, hits, sealed_hits = [], 0, 0
for req in requests:
    headers = {'Accept': 'application/json'}
    if req.get('auth', True):
        headers['X-Session-API-Key'] = key
    body = None
    if 'json' in req:
        body = json.dumps(req['json']).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    entry = {'method': req['method'], 'path': req['path']}
    t0 = time.monotonic()
    conn = http.client.HTTPConnection(host, port, timeout=float(req.get('timeout', 300)))
    try:
        conn.request(req['method'], req['path'], body=body, headers=headers)
        resp = conn.getresponse()
        text = resp.read(32 << 20).decode('utf-8', 'replace')
        entry['status'] = resp.status
        hits += text.count(key)
        text = text.replace(key, '<OH_SESSION_API_KEYS_0 redacted>')
        if sealed:
            sealed_hits += text.count(sealed)
            text = text.replace(sealed, '<sealed secret redacted>')
        try:
            value = json.loads(text) if text else None
        except ValueError:
            value = text[:4000]
        if req.get('reduce') == 'openapi-paths' and isinstance(value, dict):
            value = {p: sorted(m.upper() for m in ops if m in ('get', 'post', 'put', 'patch', 'delete'))
                     for p, ops in (value.get('paths') or {}).items() if '/api/conversations' in p}
        entry['body'] = value
    except OSError as exc:
        code = errno.errorcode.get(exc.errno) if isinstance(getattr(exc, 'errno', None), int) else None
        entry['error'] = code or type(exc).__name__
    finally:
        conn.close()
    entry['seconds'] = round(time.monotonic() - t0, 2)
    out.append(entry)
print(json.dumps(dict({'responses': out, 'session_key_occurrences': hits},
                      **({'sealed_occurrences': sealed_hits} if sealed else {})), sort_keys=True))
'''
# A secret's shape the sealed form accepts: one word of URL-safe characters (an attempt token), so
# that its repr in the script text is a plain quoted literal.
SEALED_SECRET = re.compile(r'^[A-Za-z0-9_-]{16,128}$')


def sealed_api_probe(spec, secret):
    """API_PROBE with the requests and one secret in its own text (SEALED), for standard input."""
    if not isinstance(secret, str) or not SEALED_SECRET.match(secret):
        raise Refused('REFUSED', 'the sealed secret is not one URL-safe word')
    return f'SEALED = ({spec!r}, {secret!r})\n' + API_PROBE


class GuestApi:
    """The Agent Server API, called as agent on the guest's loopback over SSH. With ``secret``
    (sealed), the requests and that secret travel in the script's text on ssh's standard input,
    never in an argument of ssh or of the guest's python3, and the secret is redacted from the
    answers (sealed_occurrences counts it)."""

    def __init__(self, ssh, profile):
        server = provisioning_config(profile)['agent_server']
        self.ssh = ssh
        self.args = [server['session_key']['guest_path'], server['listener']['address'],
                     str(server['listener']['port'])]

    def __call__(self, requests, timeout=900, secret=None):
        spec = base64.b64encode(json.dumps(requests).encode('utf-8')).decode('ascii')
        if secret is None:
            argv, script = ['python3', '-'] + self.args + [spec], API_PROBE
        else:
            argv, script = ['python3', '-'] + self.args, sealed_api_probe(spec, secret)
        result = self.ssh.run(argv, input_text=script, timeout=timeout)
        try:
            return json.loads(result.stdout.strip().splitlines()[-1])
        except (IndexError, ValueError):
            raise Refused('API', f'the API probe printed no result (rc {result.returncode}): '
                          f'{result.stderr.strip()[-500:]}')


class GuestFacts:
    """The on-demand conversation facts: request, wait, read (as agent)."""

    def __init__(self, ssh, profile):
        self.ssh = ssh
        self.facts = conversations_config(provisioning_config(profile)).get('facts') or {}

    def __call__(self):
        result = self.ssh.run(['python3', '-', self.facts['request'], self.facts['report'],
                               str(CONVERSATION_FACTS_CEILING_S)],
                              input_text=CONVERSATION_FACTS_PROBE,
                              timeout=CONVERSATION_FACTS_CEILING_S + 60)
        try:
            data = json.loads(result.stdout.strip().splitlines()[-1])
        except (IndexError, ValueError):
            data = None
        if not isinstance(data, dict) or data.get('schema') != CONVERSATION_FACTS_SCHEMA:
            raise Refused('FACTS', f'no conversation facts report (rc {result.returncode}): '
                          f'{(result.stdout or "")[-300:]} {result.stderr.strip()[-300:]}')
        return data


# The routes the lifecycle uses, as the running server's own /openapi.json names them. The
# release's openapi.json documents the local runtime; the Docker runtime's routes (stop:
# DELETE .../runtime, reopen: POST .../runtime/reprovision) are in the locked wheel's
# docker_runtime/routers.py and in the running server's document, which is checked first.
LIFECYCLE_ROUTES = (
    ('POST', '/api/conversations'),
    ('GET', '/api/conversations/{conversation_id}'),
    ('GET', '/api/conversations/search'),
    ('GET', '/api/conversations/{conversation_id}/events/search'),
    ('GET', '/api/conversations/{conversation_id}/runtime'),
    ('DELETE', '/api/conversations/{conversation_id}/runtime'),
    ('POST', '/api/conversations/{conversation_id}/runtime/reprovision'),
    ('DELETE', '/api/conversations/{conversation_id}'),
)
# Event kinds that only an LLM step produces (openhands-sdk 1.60.1 event classes): none may
# appear in a conversation that has no message and no LLM.
LLM_EVENT_KINDS = ('ActionEvent', 'MessageEvent', 'AgentErrorEvent', 'LLMCompletionLogEvent',
                   'TokenEvent', 'StreamingDeltaEvent', 'CondensationSummaryEvent', 'ObservationEvent')
EGRESS_LINE = re.compile(r'(?i)(https?://|name resolution|getaddrinfo|resolv|errno -?\d+|'
                         r'network is unreachable|no route|connecterror|connection refused|'
                         r'timed out|dns|litellm)')
CONVERSATION_STATE_KEYS = ('id', 'execution_status', 'title', 'tags', 'created_at')
# the runtime's ownership lease (taken while a container serves the conversation, released
# when it stops): not conversation state
LEASE_FILES = ('.owner_lease.lock', 'owner_lease.json')


def _status_ok(response):
    return isinstance(response, dict) and isinstance(response.get('status'), int) and \
        200 <= response['status'] < 300


def _events_of(response):
    """(id, kind, source) of an events/search page body."""
    body = (response or {}).get('body')
    items = body.get('items') if isinstance(body, dict) else None
    if not isinstance(items, list):
        return None
    return [(e.get('id'), e.get('kind'), e.get('source')) for e in items if isinstance(e, dict)]


def _state_of(response):
    body = (response or {}).get('body')
    if not isinstance(body, dict):
        return None
    out = {k: body.get(k) for k in CONVERSATION_STATE_KEYS}
    agent = body.get('agent') if isinstance(body.get('agent'), dict) else {}
    out['agent_kind'] = agent.get('kind')
    return out


def facts_summary(profile, record, report, hex_id):
    """One on-demand report, reduced to what the lifecycle compares: the conversation
    containers against the declared shape, the P7 allowance, the conversation's stored files
    and events, and the egress lines of the server's and the containers' logs."""
    view, ok = conversation_containers_view(profile, record, report)
    storage = report.get('storage') or {}
    conv_dir = (storage.get('conversations') or {}).get(hex_id)
    egress = []
    journal = report.get('server_journal') or {}
    for line in (journal.get('head') or []) + (journal.get('noted') or []):
        if EGRESS_LINE.search(line):
            egress.append({'from': 'agent-server (outer)', 'line': line})
    for cid, files in (report.get('container_files') or {}).items():
        log = (files or {}).get('log') or {}
        for line in (log.get('head') or []) + (log.get('noted') or []):
            if EGRESS_LINE.search(line):
                egress.append({'from': f'container {str(cid)[:12]}', 'line': line})
    tree = ((conv_dir or {}).get('tree') or {}).get('entries') or []
    return {
        'serial': report.get('serial'), 'collected_at': report.get('collected_at'),
        'containers': view, 'containers_ok': ok,
        'allowance': listener_allowance(profile, report),
        'conversation_dir': None if conv_dir is None else {
            k: conv_dir.get(k) for k in ('state', 'owner', 'group', 'mode')},
        'conversation_files': [{k: e.get(k) for k in ('path', 'state', 'size', 'sha256', 'mode')}
                               for e in tree],
        'events_on_disk': [(e.get('id'), e.get('kind'), e.get('source'))
                           for e in (conv_dir or {}).get('events') or []],
        'persisted_state': {e.get('path'): e.get('sha256') for e in tree
                            if e.get('state') == 'file' and e.get('path') not in LEASE_FILES},
        'runtime_control': [e.get('path', '').rsplit('/', 1)[-1]
                            for e in storage.get('runtime_control') or []],
        'runtime_data': sorted((storage.get('runtime_data') or {})),
        'container_files': {str(k)[:12]: {'resolv_conf': (v or {}).get('resolv_conf'),
                                          'hosts': (v or {}).get('hosts'),
                                          'log_lines': ((v or {}).get('log') or {}).get('lines')}
                            for k, v in (report.get('container_files') or {}).items()},
        'secret_occurrences_in_report': report.get('secret_occurrences_in_report'),
        'egress': egress,
    }


def _fixture(ctx):
    """The pinned conversation fixture (sha256 checked) and its structural problems."""
    server = provisioning_config(ctx.profile)['agent_server']
    entry = server['fixture']
    path = ctx.repo / entry['path']
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != entry['sha256']:
        raise Refused('HASH_MISMATCH', f'{entry["path"]} differs from its pinned sha256')
    body = json.loads(data.decode('utf-8'))
    checker = load_profile_checker()
    return body, checker.fixture_problems(body), checker


# tools/check_profile.py's compiled code, per process, by the sha256 of the bytes it was compiled
# from (plan leaf F-09.4): a changed file is compiled again.
_PROFILE_CHECKER_CODE = {}


def load_profile_checker():
    """tools/check_profile.py as a fresh module on every call, as before: its bytes are read and
    hashed each time and executed in a new module namespace, so no module state is shared
    between calls; only the compilation of the same bytes is reused."""
    path = REPO / 'tools' / 'check_profile.py'
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    code = _PROFILE_CHECKER_CODE.get(digest)
    if code is None:
        code = compile(data, str(path), 'exec', dont_inherit=True)
        _PROFILE_CHECKER_CODE[digest] = code
    spec = importlib.util.spec_from_file_location('check_profile', path)
    module = importlib.util.module_from_spec(spec)
    exec(code, module.__dict__)
    return module


def conversation_smoke(ctx, name, canary_dir=None, restart=False, openapi=None, out_path=None,
                       ready_timeout=READY_TIMEOUT_S, channels=None, inspect_fn=None, stop_fn=None,
                       start_fn=None):
    """conversation-smoke (F-04.2): the disposable Docker conversation of the profile's
    fixture on a running provisioned instance, over the Agent Server API as agent and the
    on-demand root facts: validate the fixture; create it (conversation_runtime docker, the
    fixed id; a non-2xx is a refusal and stops the run); inspect the conversation and its
    container against provisioning.agent_server.conversations; create it again (idempotent);
    read its events (API and disk); inspect the guest with it running; stop its runtime and
    reopen it (same id, events, state and mounts); with ``restart``, stop and start the
    guest and reopen it again; delete it. One machine verdict, PASS or FAIL.
    ``channels(record) -> (api, facts)`` and the *_fn hooks stand in for the guest in tests."""
    idir = ctx.instance_dir(name)
    _, record = running_instance(ctx, name)
    if not record.get('provisioning'):
        raise Refused('REFUSED', f'{name} was not created with --provision; it runs no Agent Server')
    out_file = None
    if out_path:
        out_file = Path(out_path).resolve()
        if os.path.lexists(out_file) or not out_file.parent.is_dir() or \
                inside(out_file, ctx.repo) or inside(out_file, idir):
            raise Refused('REFUSED', f'--out {out_path}: must be a new file in an existing '
                          'directory, outside the checkout and the instance directory')
    canaries = load_canaries(canary_dir) if canary_dir else None
    profile = ctx.profile
    body, fixture_problems, checker = _fixture(ctx)
    conversation_id = body['conversation_id']
    hex_id = conversation_id.replace('-', '')
    base = f'/api/conversations/{conversation_id}'

    def default_channels(rec):
        ssh = Ssh(profile, idir, rec['ports']['ssh'])
        return GuestApi(ssh, profile), GuestFacts(ssh, profile)
    channels = channels or default_channels
    inspect_fn = inspect_fn or (lambda: inspect(ctx, name, canaries))
    stop_fn = stop_fn or (lambda: stop(ctx, name))
    start_fn = start_fn or (lambda: start(ctx, name, ready_timeout))
    api, facts = channels(record)
    t0, started = time.time(), utc_now()
    steps, failed, stop_conditions = [], [], []
    state = {'created': False, 'deleted': False}
    caught = (Refused, OSError, ValueError, KeyError, TypeError, QmpError,
              subprocess.SubprocessError)

    def run(step, func, always=False):
        if (failed or stop_conditions) and not always:
            steps.append({'step': step, 'skipped': 'an earlier step failed'})
            return None
        s = time.time()
        entry = {'step': step, 'started_at': utc_now()}
        try:
            ok, detail = func()
        except caught as exc:
            ok, detail = False, {'error': getattr(exc, 'code', type(exc).__name__),
                                 'message': str(exc), 'detail': getattr(exc, 'detail', None)}
        entry.update(seconds=round(time.time() - s, 1), ok=bool(ok), detail=detail)
        steps.append(entry)
        log(f'conversation-smoke: {step}: {"ok" if ok else "FAILED"} ({entry["seconds"]} s)')
        if not ok:
            failed.append(step)
        return detail

    def call(*requests):
        data = api(list(requests))
        if data.get('session_key_occurrences'):
            raise Refused('SECRET', 'a response carried the session key '
                          f'({data["session_key_occurrences"]} occurrence(s), redacted)')
        return data['responses']

    def look(want_count):
        """facts now; STOP conditions (decision 0006 item 3, the mount policy) are raised."""
        summary = facts_summary(profile, record, facts(), hex_id)
        for c in summary['containers'].get('containers') or []:
            names = {p.get('check') for p in c.get('problems') or []}
            if 'image (decision 0006 item 3)' in names:
                stop_conditions.append({'condition': 'a container .Image differs from the locked '
                                        'image ID', 'container': c})
            if names & {'mount sources (declared root, no forbidden path)'}:
                stop_conditions.append({'condition': 'a mount outside the declared sources',
                                        'container': c})
        if summary['allowance']['violations']:
            stop_conditions.append({'condition': 'a Moby listener outside the P7 allowance',
                                    'violations': summary['allowance']['violations']})
        count_ok = summary['containers'].get('count') == want_count
        return summary, count_ok and summary['containers_ok'] and \
            len(summary['allowance']['allowed']) == want_count and \
            not summary['allowance']['violations']

    memo = {}

    def fixture_step():
        lines = []
        ok = not fixture_problems
        if openapi:
            schema_ok, lines = checker.validate_fixture_openapi(profile, ctx.repo, openapi)
            ok = ok and schema_ok
        return ok, {'path': provisioning_config(profile)['agent_server']['fixture']['path'],
                    'sha256': provisioning_config(profile)['agent_server']['fixture']['sha256'],
                    'structural_problems': fixture_problems,
                    'openapi': lines if openapi else 'not given (structural check only)',
                    'body': body}

    def routes_step():
        info, doc = call({'method': 'GET', 'path': '/server_info', 'auth': False},
                         {'method': 'GET', 'path': '/openapi.json', 'auth': False,
                          'reduce': 'openapi-paths'})
        server = info.get('body') if isinstance(info.get('body'), dict) else {}
        paths = doc.get('body') if isinstance(doc.get('body'), dict) else {}
        missing = [f'{m} {p}' for m, p in LIFECYCLE_ROUTES if m not in (paths.get(p) or [])]
        runtime_ok = (server.get('conversation_runtime') == 'docker' or
                      'docker' in (server.get('available_conversation_runtimes') or [])) and \
            all(c in (server.get('capabilities') or []) for c in
                ('conversation_runtime_routes_v1', 'idempotent_conversation_create_v1'))
        return _status_ok(info) and _status_ok(doc) and not missing and runtime_ok, {
            'server_info': {k: server.get(k) for k in (
                'version', 'conversation_runtime', 'available_conversation_runtimes',
                'capabilities')},
            'lifecycle_routes': {f'{m} {p}': m in (paths.get(p) or []) for m, p in LIFECYCLE_ROUTES},
            'missing': missing}

    def before_step():
        summary, ok = look(0)
        return ok and summary['conversation_dir'] is None, {'facts': summary}

    def create_step():
        response, = call({'method': 'POST', 'path': '/api/conversations', 'json': body,
                          'timeout': 600})
        memo['create'] = response
        if not _status_ok(response):
            stop_conditions.append({'condition': 'create returned non-2xx (a refusal)',
                                    'response': response})
            return False, {'response': response}
        state['created'] = True
        summary, ok = look(1)
        memo['container'] = (summary['containers'].get('containers') or [{}])[0]
        got_id = (response.get('body') or {}).get('id') if isinstance(response.get('body'), dict) \
            else None
        return ok and str(got_id).replace('-', '') == hex_id and \
            memo['container'].get('conversation') == hex_id, {
                'response': response, 'facts': summary}

    def inspect_step():
        conv, runtime = call({'method': 'GET', 'path': base}, {'method': 'GET', 'path': base + '/runtime'})
        memo['state'] = _state_of(conv)
        rt = runtime.get('body') if isinstance(runtime.get('body'), dict) else {}
        return _status_ok(conv) and _status_ok(runtime) and \
            str((memo['state'] or {}).get('id')).replace('-', '') == hex_id and \
            rt.get('runtime_status') == 'available', {
                'conversation': conv, 'runtime': runtime, 'state': memo['state'],
                'container': memo.get('container')}

    def idempotent_step():
        response, = call({'method': 'POST', 'path': '/api/conversations', 'json': body,
                          'timeout': 600})
        summary, ok = look(1)
        again = (summary['containers'].get('containers') or [{}])[0]
        got_id = (response.get('body') or {}).get('id') if isinstance(response.get('body'), dict) \
            else None
        return _status_ok(response) and ok and str(got_id).replace('-', '') == hex_id and \
            again.get('id') == (memo.get('container') or {}).get('id'), {
                'response': {'status': response.get('status'),
                             'id': got_id, 'seconds': response.get('seconds')},
                'container_before': (memo.get('container') or {}).get('id'),
                'container_after': again.get('id'), 'facts': summary}

    def events_now():
        page, = call({'method': 'GET', 'path': base + '/events/search?limit=100'})
        return page, _events_of(page)

    def events_step():
        page, events = events_now()
        summary, ok = look(1)
        memo['events'] = events
        memo['persisted'] = summary['persisted_state']
        disk = summary['events_on_disk']
        llm = [e for e in events or [] if e[1] in LLM_EVENT_KINDS]
        return _status_ok(page) and ok and events is not None and \
            sorted(map(tuple, disk)) == sorted(map(tuple, events)) and not llm and \
            {'base_state.json', 'meta.json'} <= set(memo['persisted']), {
                'api': events, 'disk': disk, 'llm_events': llm,
                'persisted_state': memo['persisted'],
                'conversation_files': summary['conversation_files'],
                'facts': summary}

    def state_kept(summary):
        before = memo.get('persisted') or {}
        return bool(before) and all(summary['persisted_state'].get(k) == v for k, v in before.items())

    def guest_inspect_step():
        rec = inspect_fn()
        verdicts = rec.get('verdicts') or {}
        want = ('profiles P3', 'profiles P4', 'profiles P6', 'profiles P7', PROVISIONING_PROPERTY)
        picked = {(p['property'], c['check']): c for p in rec.get('properties') or []
                  for c in p['checks']}
        keep = [('profiles P7', 'guest TCP listeners (Moby)'),
                ('profiles P7', 'guest TCP listeners (Agent Server)'),
                (PROVISIONING_PROPERTY, 'conversation containers'),
                (PROVISIONING_PROPERTY, 'on-demand conversation facts')]
        return all(verdicts.get(p) == 'PASS' for p in want) and \
            verdicts.get('profiles P5') in ('PASS', 'UNKNOWN'), {
                'verdicts': verdicts, 'record': rec.get('record'),
                'checks': {f'{k[0]} / {k[1]}': {x: (picked.get(k) or {}).get(x) for x in
                                                ('verdict', 'observed')} for k in keep}}

    def stop_runtime_step():
        stopped, = call({'method': 'DELETE', 'path': base + '/runtime', 'timeout': 300})
        summary, ok = look(0)
        conv, runtime = call({'method': 'GET', 'path': base}, {'method': 'GET', 'path': base + '/runtime'})
        page, events = events_now()
        rt = runtime.get('body') if isinstance(runtime.get('body'), dict) else {}
        return _status_ok(stopped) and ok and summary['conversation_dir'] is not None and \
            _status_ok(conv) and _state_of(conv) == memo.get('state') and \
            rt.get('runtime_status') == 'missing' and rt.get('can_resume') is True and \
            events == memo.get('events') and state_kept(summary), {
                'stop': stopped, 'runtime': runtime, 'state': _state_of(conv),
                'events': events, 'persisted_state_kept': state_kept(summary), 'facts': summary}

    def reopen(label):
        reopened, = call({'method': 'POST', 'path': base + '/runtime/reprovision', 'timeout': 600})
        summary, ok = look(1)
        conv, runtime = call({'method': 'GET', 'path': base}, {'method': 'GET', 'path': base + '/runtime'})
        page, events = events_now()
        now = (summary['containers'].get('containers') or [{}])[0]
        before = memo.get('container') or {}
        rt = runtime.get('body') if isinstance(runtime.get('body'), dict) else {}
        kept = events is not None and memo.get('events') is not None and \
            all(e in events for e in memo['events'])
        result = _status_ok(reopened) and ok and _status_ok(conv) and \
            _state_of(conv) == memo.get('state') and rt.get('runtime_status') == 'available' and \
            now.get('conversation') == hex_id and now.get('id') != before.get('id') and \
            now.get('mounts') == before.get('mounts') and kept and state_kept(summary) and \
            not [e for e in events or [] if e[1] in LLM_EVENT_KINDS]
        memo['container'] = now
        return result, {'reprovision': reopened, 'runtime': runtime, 'state': _state_of(conv),
                        'container_before': before.get('id'), 'container_after': now.get('id'),
                        'mounts_unchanged': now.get('mounts') == before.get('mounts'),
                        'events_retained': kept, 'events': events,
                        'persisted_state_kept': state_kept(summary),
                        'new_events': [e for e in events or [] if e not in (memo.get('events') or [])],
                        'facts': summary}

    def restart_step():
        nonlocal api, facts, record
        stopped = stop_fn()
        started_ = start_fn()
        _, record = running_instance(ctx, name)
        api, facts = channels(record)
        ok_stop = stopped.get('result') == 'stopped'
        ok_start = started_.get('result') == 'ready'
        # the facts first: the reporter's unit is ordered after aieh-agent-server.service,
        # which is active only once the server answers /ready (its completion signal)
        summary, ok = look(0)
        listed, conv, runtime = call({'method': 'GET', 'path': '/api/conversations/search?limit=100'},
                                     {'method': 'GET', 'path': base},
                                     {'method': 'GET', 'path': base + '/runtime'})
        page, events = events_now()
        items = ((listed.get('body') or {}).get('items') if isinstance(listed.get('body'), dict)
                 else None) or []
        ids = [str((i or {}).get('id')).replace('-', '') for i in items]
        rt = runtime.get('body') if isinstance(runtime.get('body'), dict) else {}
        kept = events is not None and memo.get('events') is not None and \
            all(e in events for e in memo['events'])
        return ok_stop and ok_start and ok and hex_id in ids and _status_ok(conv) and \
            _state_of(conv) == memo.get('state') and rt.get('runtime_status') == 'missing' and \
            rt.get('can_resume') is True and kept and state_kept(summary), {
                'persisted_state_kept': state_kept(summary),
                'guest_stop': {'result': stopped.get('result'), 'phases': stopped.get('phases')},
                'guest_start': {'result': started_.get('result'), 'seconds': started_.get('seconds')},
                'listed': hex_id in ids, 'runtime': runtime, 'state': _state_of(conv),
                'events_retained': kept, 'events': events, 'facts': summary}

    def delete_step():
        deleted, = call({'method': 'DELETE', 'path': base, 'timeout': 300})
        if _status_ok(deleted):
            state['deleted'] = True
        summary, ok = look(0)
        gone, = call({'method': 'GET', 'path': base})
        return _status_ok(deleted) and ok and summary['conversation_dir'] is None and \
            hex_id + '.json' not in summary['runtime_control'] and \
            hex_id not in summary['runtime_data'] and gone.get('status') == 404, {
                'delete': deleted, 'get_after': {'status': gone.get('status')}, 'facts': summary}

    run('fixture', fixture_step)
    run('routes and server_info', routes_step)
    run('facts before', before_step)
    run('create', create_step)
    run('inspect conversation', inspect_step)
    run('create again (idempotent)', idempotent_step)
    run('events', events_step)
    run('inspect guest (conversation running)', guest_inspect_step)
    run('stop runtime', stop_runtime_step)
    run('reopen', lambda: reopen('reopen'))
    if restart:
        run('restart guest', restart_step)
        run('reopen after restart', lambda: reopen('reopen after restart'))
    run('delete', delete_step)
    if state['created'] and not state['deleted']:
        cleanup = {'step': 'cleanup delete'}
        try:
            cleanup['response'] = call({'method': 'DELETE', 'path': base, 'timeout': 300})[0]
        except caught as exc:
            cleanup['error'] = f'{getattr(exc, "code", type(exc).__name__)}: {exc}'
        steps.append(cleanup)
    egress = []
    for s in steps:
        for item in (((s.get('detail') or {}).get('facts') or {}).get('egress') or []):
            if item not in egress:
                egress.append(item)
    out = {'schema': CONVERSATION_SMOKE_SCHEMA, 'operation': 'conversation-smoke',
           'labels': labels(profile), 'profile': profile['name'], 'instance': name,
           'conversation_id': conversation_id, 'restart': restart,
           'started_at': started, 'ended_at': utc_now(), 'seconds': round(time.time() - t0, 1),
           'result': 'PASS' if not failed and not stop_conditions else 'FAIL',
           'failed_steps': failed, 'stop_conditions': stop_conditions,
           'egress_lines': egress, 'steps': steps}
    out['record'] = write_record(idir, 'conversation-smoke', out)
    if out_file is not None:
        write_json_exclusive(out_file, json.loads(json.dumps(out, default=str)))
        out['out'] = str(out_file)
    return out


# ---------------------------------------------------------------- management API admission (S-01.3.1)

ADMISSION_PROBE_SCHEMA = 'ai-engineering-harness/profiles/admission-probe-record/v1'
ADMISSION_CHECK = 'management API admission (S-01.3.1)'
# The concrete values a path parameter gets in the unauthenticated sweep: an id that names
# no conversation, and a name that names nothing.
PROBE_UUID = '00000000-0000-4000-8000-0000000a0131'
PROBE_NAME = 'aieh-probe'
# The second disposable conversation (the fixture with this id): the peer of the first on
# Moby's default bridge, for the container-to-container probes.
SECOND_CONVERSATION_ID = 'a0131b00-0000-4000-8000-000000000b01'
WS_VARIANTS = ('no_auth_message', 'first_message_wrong_key', 'query_wrong_key',
               'header_wrong_key')


def admission_config(profile):
    return ((profile.get('provisioning') or {}).get('agent_server') or {}).get('admission') or {}


def load_routes(ctx):
    """The pinned route inventory (sha256 checked) and its problems (check_profile
    route_problems)."""
    entry = admission_config(ctx.profile).get('routes') or {}
    path = ctx.repo / entry['path']
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != entry.get('sha256'):
        raise Refused('HASH_MISMATCH', f'{entry["path"]} differs from its pinned sha256')
    routes = json.loads(data.decode('utf-8'))
    return routes, load_profile_checker().route_problems(routes)


def concrete_path(path):
    """A requestable path for a route template: *_id parameters get PROBE_UUID, every
    other parameter PROBE_NAME."""
    def sub(match):
        name = match.group(1).split(':')[0]
        return PROBE_UUID if name.endswith('_id') else PROBE_NAME
    return re.sub(r'\{([^}]+)\}', sub, path)


def _guard_line_ok(line, want):
    # iptables -S may append the default of an option it was not given
    # (REJECT --reject-with icmp-port-unreachable / icmp6-port-unreachable)
    return line == want or str(line).startswith(want + ' ')


def admission_check(profile, obs, record=None):
    """The guard, icc and the key check of a provisioned instance against
    provisioning.agent_server.admission, from the boot-time facts (root). An instance that
    opted into the inference composition (``record``, decision 0015) carries the
    composition's one ACCEPT after the RETURN in its families."""
    conf = admission_config(profile)
    if not conf:
        return []
    guard = (conf.get('network') or {}).get('guard') or {}
    chain = guard.get('chain')
    facts = _probe_json(obs, 'moby_facts') or {}
    adm = facts.get('admission') if isinstance(facts.get('admission'), dict) else {}
    rules = adm.get('rules') if isinstance(adm.get('rules'), dict) else {}
    families = rules.get('families') if isinstance(rules.get('families'), dict) else {}
    want_by = {tool: [f'-A {chain} {r}' for r in guard_rules_for(profile, record, tool)]
               for tool in guard.get('families') or []}
    want = [f'-A {chain} {r}' for r in guard.get('rules') or []]
    if any(w != want for w in want_by.values()):
        want = want_by
    want_jumps = sorted(f'-A INPUT -i {i} -j {chain}' for i in guard.get('interfaces') or [])
    unit = adm.get('guard_unit') if isinstance(adm.get('guard_unit'), dict) else {}
    keycheck = adm.get('keycheck') if isinstance(adm.get('keycheck'), dict) else {}
    script = keycheck.get('script') if isinstance(keycheck.get('script'), dict) else {}
    observed = {
        'guard_unit': {k: unit.get(k) for k in ('ActiveState', 'Result', 'UnitFileState')},
        'families': {tool: {'chain': (families.get(tool) or {}).get('chain'),
                            'input_jumps': (families.get(tool) or {}).get('input_jumps')}
                     for tool in guard.get('families') or []},
        'docker_requires_guard': adm.get('docker_requires_guard'),
        'docker_after_guard': adm.get('docker_after_guard'),
        'bridge_enable_icc': adm.get('bridge_enable_icc'),
        'keycheck_exec_start_pre': keycheck.get('exec_start_pre'),
        'keycheck_script': {k: script.get(k) for k in ('state', 'owner', 'group', 'mode')},
    }

    def family_ok(tool):
        f = observed['families'].get(tool) or {}
        lines, jumps = f.get('chain'), f.get('input_jumps')
        wanted = want_by.get(tool, [])
        return isinstance(lines, list) and len(lines) == len(wanted) and \
            all(_guard_line_ok(line, w) for line, w in zip(lines, wanted)) and \
            isinstance(jumps, list) and sorted(jumps) == want_jumps
    ok = bool(adm) and unit.get('ActiveState') == 'active' and \
        unit.get('UnitFileState') == 'enabled' and bool(guard.get('families')) and \
        all(family_ok(t) for t in guard.get('families')) and \
        adm.get('docker_requires_guard') is True and adm.get('docker_after_guard') is True and \
        str(adm.get('bridge_enable_icc')) == 'false' and keycheck.get('exec_start_pre') is True and \
        script.get('state') == 'file' and script.get('owner') == 'root'
    return [check(ADMISSION_CHECK, {
        'guard_unit': 'active, enabled', 'chain': want, 'input_jumps': want_jumps,
        'families': guard.get('families'), 'docker.service': f"Requires and After {guard.get('unit')}",
        'bridge_enable_icc': 'false', 'keycheck': f"ExecStartPre {conf.get('session_key', {}).get('start_check')}"},
        observed, 'facts: aieh-container-guard check, systemctl show, docker network inspect '
        'bridge (root, at boot)', ok)] + egress_check(profile, adm, unit)


CHECK_CLASSES[(PROVISIONING_PROPERTY, ADMISSION_CHECK)] = (STABLE, None)

EGRESS_CHECK = 'container egress guard (S-01.4)'


def egress_declared(profile):
    """(chain lines, hook lines, FORWARD's first rule) that the egress guard of
    provisioning.agent_server.admission.network.egress_guard installs, as iptables -S
    prints them (its allowlist between the RETURN and the LOG rule)."""
    egress = (admission_config(profile).get('network') or {}).get('egress_guard') or {}
    if not egress:
        return None
    chain, hook, rules = egress.get('chain'), egress.get('hook'), egress.get('rules') or []
    allow = [str(e.get('rule')) for e in egress.get('allowlist') or [] if isinstance(e, dict)]
    return ([f'-A {chain} {r}' for r in rules[:1] + allow + rules[1:]],
            [f'-A {hook} {r}' for r in egress.get('hook_rules') or []],
            f'-A FORWARD -j {hook}')


def egress_check(profile, adm, unit):
    """S-01.4: the egress guard of a provisioned instance from the boot-time facts (root,
    after docker.service): in both families its chain, DOCKER-USER's hook rules and FORWARD's
    first jump are the declared ones; they equal what the guard printed when it installed them
    at this boot, before Moby started (they survived Moby's start); and the guard's unit exited
    before docker.service started."""
    declared = egress_declared(profile)
    if declared is None:
        return []
    want_chain, want_hook, want_jump = declared
    egress = (admission_config(profile).get('network') or {}).get('egress_guard') or {}
    rules = adm.get('rules') if isinstance(adm.get('rules'), dict) else {}
    families = rules.get('families') if isinstance(rules.get('families'), dict) else {}
    install = adm.get('guard_install') if isinstance(adm.get('guard_install'), dict) else {}
    installed = install.get('families') if isinstance(install.get('families'), dict) else {}
    order = adm.get('order') if isinstance(adm.get('order'), dict) else {}

    def view(fam):
        e = (fam or {}).get('egress') if isinstance((fam or {}).get('egress'), dict) else {}
        return {k: e.get(k) for k in ('chain', 'hook', 'forward_head', 'forward_jumps',
                                      'forward_policy')}
    try:
        ordered = 0 < int(order.get('guard_exit_monotonic')) < int(order.get('docker_start_monotonic'))
    except (TypeError, ValueError):
        ordered = False
    # the order as a fact, not its per-boot monotonic times: this check is stable across a
    # start and a recreate (E-01.2.2 slice (c), finding F-14)
    observed = {'families': {t: view(families.get(t)) for t in egress.get('families') or []},
                'installed_before_docker': {t: view(installed.get(t))
                                            for t in egress.get('families') or []},
                'guard_exited_before_docker_started': ordered,
                'guard_unit': unit.get('ActiveState')}

    def family_ok(f):
        lines, hook, head = f.get('chain'), f.get('hook'), f.get('forward_head')
        return isinstance(lines, list) and len(lines) == len(want_chain) and \
            all(_guard_line_ok(line, w) for line, w in zip(lines, want_chain)) and \
            hook == want_hook and isinstance(head, list) and head[:1] == [want_jump] and \
            f.get('forward_jumps') == 1

    def survived(t):
        before, after = observed['installed_before_docker'][t], observed['families'][t]
        return before.get('chain') == after.get('chain') and before.get('hook') == after.get('hook')
    tools = egress.get('families') or []
    ok = bool(tools) and unit.get('ActiveState') == 'active' and \
        all(family_ok(observed['families'][t]) for t in tools) and \
        install.get('ok') is True and install.get('egress_ok') is True and \
        all(survived(t) for t in tools) and ordered
    return [check(EGRESS_CHECK, {
        'chain': want_chain, 'hook': want_hook, 'forward_first_rule': want_jump,
        'forward_jumps': 1, 'families': tools, 'allowlist': egress.get('allowlist'),
        'installed_before_docker': 'the same chain and hook rules, printed by the guard unit '
                                   'at this boot before docker.service started'},
        observed, 'facts: aieh-container-guard check after docker.service, the guard unit\'s '
        'install line in the journal, systemctl show (root, at boot)', ok)]


CHECK_CLASSES[(PROVISIONING_PROPERTY, EGRESS_CHECK)] = (STABLE, None)


QUIESCE_CHECK = 'Agent Server quiesce step (E-01.2.2)'


def quiesce_config(profile):
    return ((profile.get('provisioning') or {}).get('agent_server') or {}).get('quiesce') or {}


def _monotonic(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def quiesce_check(profile, obs):
    """E-01.2.2 (findings F-1, F-2): the quiesce step of a provisioned instance against
    provisioning.agent_server.quiesce and the server's dependencies, from the boot facts
    (root): the unit's settings, the server's Requires and After (no Wants), the script and
    the quarantine directory, and this boot's last run: it succeeded, left no container and
    exited before the server's ExecStart."""
    conf = quiesce_config(profile)
    if not conf:
        return []
    server = (profile.get('provisioning') or {}).get('agent_server') or {}
    deps = (server.get('service') or {}).get('dependencies') or {}
    settings = conf.get('unit_settings') or {}
    quarantine = conf.get('quarantine') or {}
    facts = _probe_json(obs, 'moby_facts') or {}
    q = facts.get('quiesce') if isinstance(facts.get('quiesce'), dict) else {}
    unit = q.get('unit') if isinstance(q.get('unit'), dict) else {}
    srv = q.get('server') if isinstance(q.get('server'), dict) else {}
    last = q.get('last') if isinstance(q.get('last'), dict) else {}

    def present(text, names):
        tokens = str(text or '').split()
        return [n for n in names if n in tokens]
    stat_keys = ('state', 'owner', 'group', 'mode')
    script = q.get('script') if isinstance(q.get('script'), dict) else {}
    qdir = q.get('quarantine') if isinstance(q.get('quarantine'), dict) else {}
    exit_at = _monotonic(unit.get('ExecMainExitTimestampMonotonic'))
    start_at = _monotonic(srv.get('ExecMainStartTimestampMonotonic'))
    observed = {
        'unit': {k: unit.get(k) for k in ('LoadState', 'Type', 'RemainAfterExit', 'Result')},
        'unit_requires': present(unit.get('Requires'), settings.get('Requires') or []),
        'unit_after': present(unit.get('After'), settings.get('After') or []),
        'unit_before': present(unit.get('Before'), settings.get('Before') or []),
        'server_requires': present(srv.get('Requires'), deps.get('requires') or []),
        'server_after': present(srv.get('After'), deps.get('after') or []),
        'server_wants_docker': 'docker.service' in str(srv.get('Wants') or '').split(),
        'script': {k: script.get(k) for k in stat_keys},
        'quarantine': {k: qdir.get(k) for k in stat_keys},
        'ran_this_boot': _monotonic(q.get('runs_this_boot')) >= 1,
        'last_run': {k: last.get(k) for k in ('ok', 'containers_remaining')},
        'exited_before_server_exec_start': 0 < exit_at <= start_at,
    }
    declared = {
        'unit': {'LoadState': 'loaded', 'Type': settings.get('Type'),
                 'RemainAfterExit': settings.get('RemainAfterExit'), 'Result': 'success'},
        'unit_requires': settings.get('Requires'), 'unit_after': settings.get('After'),
        'unit_before': settings.get('Before'),
        'server_requires': deps.get('requires'), 'server_after': deps.get('after'),
        'server_wants_docker': False,
        'script': {'state': 'file', 'owner': 'root', 'group': 'root', 'mode': '755'},
        'quarantine': {'state': 'directory', 'owner': quarantine.get('owner'),
                       'group': quarantine.get('group'), 'mode': quarantine.get('mode')},
        'ran_this_boot': True, 'last_run': {'ok': True, 'containers_remaining': 0},
        'exited_before_server_exec_start': True,
        'invariant': conf.get('invariant')}
    ok = bool(unit) and all(observed[k] == declared[k] for k in observed)
    return [check(QUIESCE_CHECK, declared, observed,
                  'facts: systemctl show of the quiesce and server units, stat of the script and '
                  'the quarantine, the step\'s last journal summary of this boot (root, at boot)',
                  ok)]


CHECK_CLASSES[(PROVISIONING_PROPERTY, QUIESCE_CHECK)] = (STABLE, None)

START_CHECK = 'Agent Server start (E-01.4.3)'
READY_PREFIX = 'aieh-agent-server-ready: '


def ready_outcome(line):
    """{'ready': bool, 'start': class, 'seconds': float|None, 'restarts': str|None,
    'last_status': str|None} of one outcome line of the readiness wait
    (provisioning.agent_server.service.readiness), or None for any other line."""
    text = str(line or '')
    at = text.find(READY_PREFIX)
    if at < 0:
        return None
    words = text[at + len(READY_PREFIX):].split()
    if words[:1] == ['ready']:
        ready, rest = True, words[1:]
    elif words[:2] == ['not', 'ready']:
        ready, rest = False, words[2:]
    else:
        return None
    fields = dict(w.split('=', 1) for w in rest if '=' in w)
    if 'start' not in fields:
        return None
    try:
        seconds = float(fields.get('seconds'))
    except (TypeError, ValueError):
        seconds = None
    return {'ready': ready, 'start': fields['start'], 'seconds': seconds,
            'restarts': fields.get('restarts'), 'last_status': fields.get('last_status')}


def start_race_config(profile):
    return ((profile.get('provisioning') or {}).get('agent_server') or {}).get('start_race') or {}


def start_check(profile, obs):
    """E-01.4.3: the start-race control and this boot's start of the Agent Server, from the
    boot facts (root): the control variable in the unit's environment and in every server
    process's (names only), the unit's NRestarts, and the readiness wait's last outcome line
    of this boot, which must say start=clean (a retried, slow or unverified start never
    passes as clean)."""
    conf = start_race_config(profile)
    if not conf:
        return []
    control = conf.get('control') or {}
    var, value = control.get('variable'), control.get('value')
    facts = _probe_json(obs, 'moby_facts') or {}
    server = facts.get('agent_server') if isinstance(facts.get('agent_server'), dict) else {}
    unit = server.get('unit') if isinstance(server.get('unit'), dict) else {}
    procs = server.get('processes') if isinstance(server.get('processes'), list) else []
    start = server.get('start') if isinstance(server.get('start'), dict) else {}
    # the boot's last outcome line decides; one that does not parse is no clean start
    lines = start.get('last') if isinstance(start.get('last'), list) else []
    outcome = ready_outcome(lines[-1]) if lines else None
    observed = {
        'unit_environment': f'{var}={value}' in str(unit.get('Environment') or '').split(),
        'processes_with_variable': sorted({var in (p.get('environment_names') or [])
                                           for p in procs}),
        'NRestarts': unit.get('NRestarts'),
        'last_outcome': None if outcome is None else
        {'ready': outcome['ready'], 'start': outcome['start'], 'restarts': outcome['restarts']},
        'outcome_lines_this_boot': start.get('count'),
    }
    declared = {
        'unit_environment': True, 'processes_with_variable': [True], 'NRestarts': '0',
        'last_outcome': {'ready': True, 'start': 'clean', 'restarts': '0'},
        'outcome_lines_this_boot': 'at least 1'}
    ok = bool(unit) and start.get('rc') == 0 and \
        all(observed[k] == declared[k] for k in declared if k != 'outcome_lines_this_boot') and \
        isinstance(start.get('count'), int) and start['count'] >= 1
    return [check(START_CHECK, declared, observed,
                  "facts: systemctl show of the server unit, /proc/<pid>/environ names, the "
                  "readiness wait's outcome lines of this boot (journalctl -b -u, root, at boot)",
                  ok)]


CHECK_CLASSES[(PROVISIONING_PROPERTY, START_CHECK)] = (STABLE, None)

# Run as agent: the unauthenticated sweep of every route of the inventory (HTTP: without a
# key and with a wrong one; WebSocket: four refusals), and the running server's own
# /openapi.json reduced to its operations. The session key is read from its file only to
# count and redact any occurrence in a response; it is never sent.
ADMISSION_SWEEP = r'''import base64, http.client, json, os, secrets, socket, struct, sys, time
key_path, host, port, spec = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
spec = json.loads(base64.b64decode(spec).decode('utf-8'))
with open(key_path, encoding='ascii') as handle:
    key = handle.read().strip()
wrong = secrets.token_urlsafe(32)
hits = 0
def text_of(raw):
    global hits
    text = raw.decode('utf-8', 'replace')
    hits += text.count(key)
    return text.replace(key, '<redacted>')
def http_req(method, path, headers=None):
    conn = http.client.HTTPConnection(host, port, timeout=60)
    try:
        conn.request(method, path, headers=headers or {})
        resp = conn.getresponse()
        return [resp.status, text_of(resp.read(1 << 16))[:160]]
    except OSError as exc:
        return [None, type(exc).__name__]
    finally:
        conn.close()
def frame(op, payload):
    mask = os.urandom(4)
    head = bytes([0x80 | op, 0x80 | len(payload)])
    return head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
def ws(path, auth=None, header_key=None):
    t0 = time.monotonic()
    out = {}
    try:
        s = socket.create_connection((host, port), timeout=60)
    except OSError as exc:
        return {'error': type(exc).__name__}
    try:
        req = ('GET ' + path + ' HTTP/1.1\r\nHost: ' + host + ':' + str(port) +
               '\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: ' +
               base64.b64encode(os.urandom(16)).decode() + '\r\nSec-WebSocket-Version: 13\r\n')
        if header_key:
            req += 'X-Session-API-Key: ' + header_key + '\r\n'
        s.sendall((req + '\r\n').encode())
        buf = b''
        while b'\r\n\r\n' not in buf:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
        head, _, rest = buf.partition(b'\r\n\r\n')
        line = head.split(b'\r\n')[0].decode('latin-1').split()
        out['handshake'] = int(line[1]) if len(line) > 1 and line[1].isdigit() else None
        if out['handshake'] == 101:
            if auth is not None:
                s.sendall(frame(1, json.dumps(auth).encode()))
            data = rest
            while len(data) < 2:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
            if len(data) >= 2:
                n = data[1] & 0x7f
                while len(data) < 2 + n:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                payload = data[2:2 + n]
                out['opcode'] = data[0] & 0x0f
                if out['opcode'] == 8 and len(payload) >= 2:
                    out['close_code'] = struct.unpack('!H', payload[:2])[0]
                    out['close_reason'] = text_of(payload[2:])
                else:
                    out['payload'] = text_of(payload)[:120]
    except OSError as exc:
        out['error'] = type(exc).__name__
    finally:
        s.close()
    out['seconds'] = round(time.monotonic() - t0, 2)
    return out
conn = http.client.HTTPConnection(host, port, timeout=60)
conn.request('GET', '/openapi.json')
doc = json.loads(text_of(conn.getresponse().read()))
conn.close()
openapi = {p: sorted(m.upper() for m in item if m in ('get', 'post', 'put', 'patch', 'delete', 'head', 'options'))
           for p, item in (doc.get('paths') or {}).items()}
out = {'openapi': openapi, 'openapi_version': (doc.get('info') or {}).get('version'), 'http': [], 'ws': []}
for method, path in spec['http']:
    out['http'].append({'method': method, 'path': path, 'no_key': http_req(method, path),
                        'wrong_key': http_req(method, path, {'X-Session-API-Key': wrong})})
for path in spec['ws']:
    out['ws'].append({'path': path, 'no_auth_message': ws(path),
                      'first_message_wrong_key': ws(path, {'type': 'auth', 'session_api_key': wrong}),
                      'query_wrong_key': ws(path + '?session_api_key=' + wrong),
                      'header_wrong_key': ws(path, header_key=wrong)})
out['session_key_occurrences'] = hits
print(json.dumps(out, sort_keys=True))
'''

# Run inside a conversation container (through the outer server's proxy to the inner
# server's bash route: the vantage of the agent's own terminal). One TCP connect per target,
# with a 4 s ceiling, and for a connected one the first line of the answer to GET /server_info.
CONTAINER_NET_PROBE = r'''probe() {
  r=$(timeout 4 bash -c "exec 3<>/dev/tcp/$1/$2 && printf 'GET /server_info HTTP/1.0\r\nHost: x\r\n\r\n' >&3 && timeout 2 head -c 64 <&3 | head -n 1" 2>&1)
  rc=$?
  r=$(printf '%s' "$r" | tr -d '\r' | tr '\n' ' ' | head -c 160)
  [ $rc -eq 124 ] && r=TIMEOUT
  echo "PROBE $1 $2 rc=$rc $r"
}
echo "ID $(id -u):$(id -g)"
echo "ADDR $(hostname -I)"
echo "HOSTS_HDI $(awk '$2 == "host.docker.internal" {print $1}' /etc/hosts)"
for t in $TARGETS; do probe "${t%:*}" "${t##*:}"; done
'''

# Run inside a conversation container: where the start_child_conversation tool sends its
# request, which session keys the agent's processes can read (fingerprints only), and what
# its own inner server and the outer listener answer with that key. The inner key goes into
# a 0600 header file inside the container (never a command line) and is removed after.
CONTAINER_KEY_PROBE = r'''fp() { printf 'aieh-secret-fingerprint/v1\n%s' "$1" | sha256sum | cut -c1-64; }
echo "INTERNAL_URL $OH_INTERNAL_SERVER_URL"
for d in /proc/[0-9]*; do
  [ -r "$d/environ" ] || continue
  for v in OH_SESSION_API_KEYS_0 OH_SECRET_KEY SESSION_API_KEY; do
    val=$(tr '\0' '\n' < "$d/environ" 2>/dev/null | sed -n "s/^$v=//p" | head -n 1)
    [ -n "$val" ] && echo "FP $v $(fp "$val")"
  done
done
umask 077
code() { rm -f /tmp/aieh-body; c=$(curl -s -o /tmp/aieh-body -w '%{http_code}' --max-time 10 "$@"); echo "$c $(head -c 160 /tmp/aieh-body 2>/dev/null | tr '\n' ' ')"; }
U="$OH_INTERNAL_SERVER_URL/api/conversations/$CID/children"
printf 'X-Session-API-Key: %s\n' "$(tr '\0' '\n' < /proc/1/environ | sed -n 's/^OH_SESSION_API_KEYS_0=//p')" > /tmp/aieh-hdr
echo "CHILD_NO_KEY $(code -X POST -H 'Content-Type: application/json' -d '{}' "$U")"
echo "CHILD_INNER_KEY $(code -X POST -H @/tmp/aieh-hdr -H 'Content-Type: application/json' -d '{}' "$U")"
for h in $OUTER; do echo "OUTER_WITH_INNER_KEY $h $(code -H @/tmp/aieh-hdr "http://$h/api/conversations/count")"; done
rm -f /tmp/aieh-hdr /tmp/aieh-body
echo DONE
'''

# Run as agent: the seeded key check under synthetic environments (no real secret). Each
# case: the variables given, the exit status and the printed line.
KEYCHECK_PROBE = r'''import json, subprocess, sys
script = sys.argv[1]
a, b = 'A' * 43, 'B' * 43
cases = {'no key': {}, 'empty key': {'OH_SESSION_API_KEYS_0': '', 'OH_SECRET_KEY': b},
         'short key': {'OH_SESSION_API_KEYS_0': 'x' * 8, 'OH_SECRET_KEY': b},
         'no secret key': {'OH_SESSION_API_KEYS_0': a},
         'equal values': {'OH_SESSION_API_KEYS_0': a, 'OH_SECRET_KEY': a},
         'second key': {'OH_SESSION_API_KEYS_0': a, 'OH_SECRET_KEY': b, 'OH_SESSION_API_KEYS_1': a},
         'legacy key': {'OH_SESSION_API_KEYS_0': a, 'OH_SECRET_KEY': b, 'SESSION_API_KEY': a},
         'valid': {'OH_SESSION_API_KEYS_0': a, 'OH_SECRET_KEY': b}}
out = {}
for name, env in cases.items():
    env = dict(env, PATH='/usr/bin:/bin')
    r = subprocess.run(['/usr/bin/python3', '-I', script], env=env, capture_output=True, text=True, timeout=60)
    out[name] = {'rc': r.returncode, 'line': (r.stdout or r.stderr).strip()[-300:]}
print(json.dumps(out, sort_keys=True))
'''


def _probe_lines(stdout, tag):
    return [line.split(' ', 1)[1] if ' ' in line else '' for line in (stdout or '').splitlines()
            if line.startswith(tag + ' ') or line == tag]


def _net_outcome(rc, text):
    if rc == 0 and text and 'TIMEOUT' not in text:
        return 'connected'
    if 'TIMEOUT' in text or rc == 124:
        return 'timeout'
    if 'refused' in text.lower():
        return 'refused'
    if 'no route' in text.lower() or 'unreachable' in text.lower():
        return 'unreachable'
    return 'error'


def parse_net_probe(stdout):
    """{'host:port': {'outcome', 'rc', 'answer'}} of CONTAINER_NET_PROBE's PROBE lines."""
    out = {}
    for rest in _probe_lines(stdout, 'PROBE'):
        parts = rest.split(' ', 3)
        if len(parts) < 3 or not parts[2].startswith('rc='):
            continue
        host, port, rc = parts[0], parts[1], parts[2][3:]
        text = parts[3] if len(parts) > 3 else ''
        rc = int(rc) if rc.lstrip('-').isdigit() else None
        out[f'{host}:{port}'] = {'outcome': _net_outcome(rc, text), 'rc': rc, 'answer': text[:120]}
    return out


def admission_probe(ctx, name, out_path=None, channels=None, ssh_fn=None):
    """admission-probe (S-01.3.1) on a running provisioned instance: the route inventory
    against the running server's /openapi.json; every route without a key and with a
    wrong one (HTTP and WebSocket); the trusted side with the key; two disposable
    conversations, and from inside each container (the agent's own terminal, through the
    outer server's proxied bash route) the management listener, the guest's services, the
    published ports and the peer container at every address the container can see; the
    session keys the agent's processes can read; where start_child_conversation sends its
    request; the seeded key check; what the guard and the server logged. One machine
    verdict, PASS or FAIL. A key-gated route that answers 2xx without the key is a stop
    condition. ``channels(record) -> (api, facts)`` and ``ssh_fn(record)`` stand in for the
    guest in tests."""
    idir = ctx.instance_dir(name)
    _, record = running_instance(ctx, name)
    if not record.get('provisioning'):
        raise Refused('REFUSED', f'{name} was not created with --provision; it runs no Agent Server')
    conf = admission_config(ctx.profile)
    if not conf:
        raise Refused('REFUSED', 'the profile declares no provisioning.agent_server.admission')
    out_file = None
    if out_path:
        out_file = Path(out_path).resolve()
        if os.path.lexists(out_file) or not out_file.parent.is_dir() or \
                inside(out_file, ctx.repo) or inside(out_file, idir):
            raise Refused('REFUSED', f'--out {out_path}: must be a new file in an existing '
                          'directory, outside the checkout and the instance directory')
    profile = ctx.profile
    server = provisioning_config(profile)['agent_server']
    listener = server['listener']
    routes, inventory_problems = load_routes(ctx)
    body_a, fixture_problems, _ = _fixture(ctx)
    body_b = dict(body_a, conversation_id=SECOND_CONVERSATION_ID,
                  tags={'aieh': 's-01.3.1-disposable-peer'})
    conversations = [body_a['conversation_id'], SECOND_CONVERSATION_ID]

    def default_channels(rec):
        ssh = Ssh(profile, idir, rec['ports']['ssh'])
        return GuestApi(ssh, profile), GuestFacts(ssh, profile)
    channels = channels or default_channels
    ssh = (ssh_fn or (lambda rec: Ssh(profile, idir, rec['ports']['ssh'])))(record)
    api, facts = channels(record)
    t0, started = time.time(), utc_now()
    steps, failed, stop_conditions = [], [], []
    state = {'created': []}
    memo = {}
    caught = (Refused, OSError, ValueError, KeyError, TypeError, IndexError,
              subprocess.SubprocessError)

    def run(step, func, always=False):
        if (failed or stop_conditions) and not always:
            steps.append({'step': step, 'skipped': 'an earlier step failed'})
            return None
        s = time.time()
        entry = {'step': step, 'started_at': utc_now()}
        try:
            ok, detail = func()
        except caught as exc:
            ok, detail = False, {'error': getattr(exc, 'code', type(exc).__name__),
                                 'message': str(exc), 'detail': getattr(exc, 'detail', None)}
        entry.update(seconds=round(time.time() - s, 1), ok=bool(ok), detail=detail)
        steps.append(entry)
        log(f'admission-probe: {step}: {"ok" if ok else "FAILED"} ({entry["seconds"]} s)')
        if not ok:
            failed.append(step)
        return detail

    def call(*requests):
        data = api(list(requests))
        if data.get('session_key_occurrences'):
            raise Refused('SECRET', 'a response carried the session key '
                          f'({data["session_key_occurrences"]} occurrence(s), redacted)')
        return data['responses']

    def guest_json(script, args, timeout=900):
        result = ssh.run(['python3', '-'] + [str(a) for a in args], input_text=script,
                         timeout=timeout)
        try:
            return json.loads(result.stdout.strip().splitlines()[-1])
        except (IndexError, ValueError):
            raise Refused('PROBE', f'the guest probe printed no result (rc {result.returncode}): '
                          f'{result.stderr.strip()[-500:]}')

    def in_container(conversation, command, timeout=120):
        response, = call({'method': 'POST',
                          'path': f'/api/conversations/{conversation}/bash/execute_bash_command',
                          'json': {'command': command, 'cwd': '/workspace', 'timeout': timeout},
                          'timeout': timeout + 60})
        body = response.get('body') if isinstance(response.get('body'), dict) else {}
        if not _status_ok(response) or body.get('exit_code') is None:
            raise Refused('CONTAINER', f'the command did not run in {conversation}: '
                          f'{json.dumps(response)[:400]}')
        return body.get('stdout') or ''

    def inventory_step():
        live = guest_json(ADMISSION_SWEEP, [server['session_key']['guest_path'],
                                            listener['address'], listener['port'],
                                            base64.b64encode(json.dumps(
                                                {'http': [], 'ws': []}).encode()).decode()])
        doc = {(m, p) for p, ms in (live.get('openapi') or {}).items() for m in ms}
        listed = {(r['method'], r['path']) for r in routes['routes'] if r.get('source') == 'openapi'}
        memo['openapi_ops'] = len(doc)
        missing, extra = sorted(doc - listed), sorted(listed - doc)
        return not inventory_problems and not missing and not extra and \
            live.get('openapi_version') == routes.get('version'), {
                'inventory': {'path': conf['routes']['path'], 'sha256': conf['routes']['sha256'],
                              'routes': len(routes['routes']), 'problems': inventory_problems},
                'running_openapi': {'version': live.get('openapi_version'),
                                    'paths': len(live.get('openapi') or {}), 'operations': len(doc)},
                'in_document_not_in_inventory': [f'{m} {p}' for m, p in missing],
                'in_inventory_not_in_document': [f'{m} {p}' for m, p in extra]}

    def sweep_step():
        http = [(r['method'], concrete_path(r['path'])) for r in routes['routes']
                if r['method'] != 'WEBSOCKET']
        ws_paths = [concrete_path(r['path']) for r in routes['routes'] if r['method'] == 'WEBSOCKET']
        live = guest_json(ADMISSION_SWEEP, [server['session_key']['guest_path'],
                                            listener['address'], listener['port'],
                                            base64.b64encode(json.dumps(
                                                {'http': http, 'ws': ws_paths}).encode()).decode()],
                          timeout=1800)
        if live.get('session_key_occurrences'):
            raise Refused('SECRET', 'a refused response carried the session key')
        got_http = {(e['method'], e['path']): e for e in live.get('http') or []}
        got_ws = {e['path']: e for e in live.get('ws') or []}
        mismatches, summary, statuses = [], {}, {}
        for r in routes['routes']:
            key = f"{r['method']} {r['path']}"
            if r['method'] == 'WEBSOCKET':
                e = got_ws.get(concrete_path(r['path'])) or {}
                seen = {}
                for variant in WS_VARIANTS:
                    v = e.get(variant) or {}
                    seen[variant] = v.get('close_code') if v.get('handshake') == 101 else v.get('handshake')
                want = r['expect']
                if 'handshake' in want:
                    good = all(seen[v] == want['handshake'] for v in WS_VARIANTS)
                else:
                    good = all(seen.get(v) == want.get(v) for v in WS_VARIANTS)
                if any((e.get(v) or {}).get('handshake') == 101 and
                       (e.get(v) or {}).get('opcode') != 8 for v in WS_VARIANTS):
                    stop_conditions.append({'condition': 'a WebSocket route stayed open without '
                                            'the key', 'route': key, 'observed': e})
            else:
                e = got_http.get((r['method'], concrete_path(r['path']))) or {}
                seen = {'no_key': (e.get('no_key') or [None])[0],
                        'wrong_key': (e.get('wrong_key') or [None])[0]}
                good = seen == r['expect']
                if r['admission'] != 'public' and any(isinstance(s, int) and 200 <= s < 300
                                                     for s in seen.values()):
                    stop_conditions.append({'condition': 'a privileged route answered 2xx '
                                            'without the key', 'route': key, 'observed': e})
            statuses[key] = seen
            label = f"{r['admission']} -> {json.dumps(seen, sort_keys=True)}"
            summary[label] = summary.get(label, 0) + 1
            if not good:
                mismatches.append({'route': key, 'expected': r['expect'], 'observed': seen,
                                   'answer': e})
        return not mismatches, {'routes': len(routes['routes']), 'outcomes': summary,
                                'mismatches': mismatches, 'statuses': statuses}

    def trusted_step():
        count, info, search = call({'method': 'GET', 'path': '/api/conversations/count'},
                                   {'method': 'GET', 'path': '/server_info', 'auth': False},
                                   {'method': 'GET', 'path': '/api/conversations/search?limit=10'})
        memo['count_before'] = count.get('body')
        return _status_ok(count) and _status_ok(info) and _status_ok(search) and \
            count.get('body') == 0, {
                'count': {'status': count.get('status'), 'body': count.get('body')},
                'server_info': {'status': info.get('status')},
                'search': {'status': search.get('status')}}

    def create_step():
        out = {}
        for body in (body_a, body_b):
            response, = call({'method': 'POST', 'path': '/api/conversations', 'json': body,
                              'timeout': 600})
            out[body['conversation_id']] = {'status': response.get('status'),
                                            'seconds': response.get('seconds')}
            if not _status_ok(response):
                stop_conditions.append({'condition': 'create returned non-2xx (a refusal)',
                                        'response': response})
                return False, out
            state['created'].append(body['conversation_id'])
        report = facts()
        view, ok = conversation_containers_view(profile, record, report)
        allowance = listener_allowance(profile, report)
        memo['published'] = sorted({str(a.get('local', '')).rpartition(':')[2]
                                    for a in allowance.get('allowed') or [] if a.get('local')})
        return ok and view.get('count') == 2 and not allowance['violations'] and \
            not fixture_problems, {'create': out, 'containers': view, 'allowance': allowance}

    def addresses():
        result = ssh.run(['ip', '-o', '-4', 'address', 'show'], timeout=60)
        addrs = []
        for line in result.stdout.splitlines():
            parts = line.split()
            if 'inet' in parts:
                addr = parts[parts.index('inet') + 1].split('/')[0]
                if not addr.startswith('127.'):
                    addrs.append(addr)
        return sorted(addrs)

    def network_step():
        guest_addrs = addresses()
        memo['guest_addresses'] = guest_addrs
        results, ok_all = {}, True
        ips = {}
        for cid in conversations:
            ips[cid] = (in_container(cid, 'hostname -I', 30).split() or [None])[0]
        for cid in conversations:
            peer = ips[conversations[1 - conversations.index(cid)]]
            targets = []                                  # (host, port, what, allowed outcomes)
            for host in ['host.docker.internal'] + guest_addrs:
                targets.append((host, listener['port'], 'management listener', {'refused'}))
                targets.append((host, 22, 'guest sshd', {'refused'}))
                targets.append((host, 5355, 'guest LLMNR (systemd-resolved)', {'refused'}))
                for port in memo.get('published') or []:
                    targets.append((host, int(port), 'a published conversation port', {'refused'}))
            targets.append((peer, 8000, 'peer container inner server', {'timeout', 'unreachable'}))
            targets.append((peer, 8001, 'peer container VSCode', {'timeout', 'unreachable'}))
            targets.append(('127.0.0.1', 8000, 'own inner server (control)', {'connected'}))
            spec = ' '.join(f'{h}:{p}' for h, p, _, _ in targets)
            text = in_container(cid, f'TARGETS="{spec}"\n' + CONTAINER_NET_PROBE, 120)
            parsed = parse_net_probe(text)
            rows = []
            for host, port, what, allowed in targets:
                got = parsed.get(f'{host}:{port}') or {'outcome': 'missing'}
                good = got['outcome'] in allowed
                ok_all = ok_all and good
                rows.append({'target': f'{host}:{port}', 'what': what, 'expected': sorted(allowed),
                             'observed': got['outcome'], 'answer': got.get('answer'), 'ok': good})
                if what == 'management listener' and got['outcome'] == 'connected':
                    stop_conditions.append({'condition': 'the management listener answered '
                                            'from a conversation container', 'target': rows[-1]})
            hdi = (_probe_lines(text, 'HOSTS_HDI') or [''])[0]
            results[cid] = {'container_address': ips[cid], 'host.docker.internal': hdi,
                            'identity': (_probe_lines(text, 'ID') or [''])[0], 'targets': rows}
        return ok_all, {'guest_addresses': guest_addrs, 'published_ports': memo.get('published'),
                        'containers': results}

    def custody_step():
        boot = guest_json('import json,sys\nprint(json.dumps(json.load(open(sys.argv[1]))))\n',
                          [provisioning_config(profile)['facts']['path']], 120)
        outer = ((boot.get('agent_server') or {}).get('secrets') or {}).get('fingerprints') or {}
        outer_hosts = ' '.join(f'{h}:{listener["port"]}' for h in
                               ['host.docker.internal'] + (memo.get('guest_addresses') or []))
        results, ok_all = {}, bool(outer)
        for cid in conversations:
            text = in_container(cid, f'CID={cid}\nOUTER="{outer_hosts}"\n' + CONTAINER_KEY_PROBE, 120)
            prints = sorted({tuple(x.split(' ', 1)) for x in _probe_lines(text, 'FP')})
            leaked = [name for name, fp in prints if fp in set(outer.values())]
            child = {'no_key': (_probe_lines(text, 'CHILD_NO_KEY') or [''])[0][:160],
                     'inner_key_empty_body': (_probe_lines(text, 'CHILD_INNER_KEY') or [''])[0][:160]}
            outer_tries = _probe_lines(text, 'OUTER_WITH_INNER_KEY')
            internal = (_probe_lines(text, 'INTERNAL_URL') or [''])[0]
            good = not leaked and bool(prints) and internal.startswith('http://127.0.0.1:') and \
                child['no_key'].startswith('401') and child['inner_key_empty_body'].startswith('422') and \
                bool(outer_tries) and all(t.split(' ')[1] == '000' for t in outer_tries if ' ' in t)
            ok_all = ok_all and good
            results[cid] = {'internal_server_url': internal,
                            'readable_key_fingerprints': [{'variable': n, 'fingerprint': f}
                                                          for n, f in prints],
                            'outer_fingerprint_found': leaked,
                            'start_child_conversation_target': child,
                            'outer_listener_with_inner_key': outer_tries, 'ok': good}
        count, = call({'method': 'GET', 'path': '/api/conversations/count'})
        return ok_all and count.get('body') == 2, {
            'outer_fingerprints': outer, 'containers': results,
            'outer_count_after': count.get('body')}

    def keycheck_step():
        path = conf['session_key']['start_check']
        cases = guest_json(KEYCHECK_PROBE, [path], 120)
        good = all(v.get('rc') == 1 and 'refused' in v.get('line', '')
                   for k, v in cases.items() if k != 'valid') and \
            (cases.get('valid') or {}).get('rc') == 0
        return good, {'script': path, 'cases': cases}

    def logged_step():
        report = facts()
        adm = report.get('admission') if isinstance(report.get('admission'), dict) else {}
        counters = {t: adm.get(t) for t in ('iptables', 'ip6tables')}
        rejected = sum(r.get('packets', 0) for r in (counters.get('iptables') or [])
                       if isinstance(r, dict) and r.get('target') in ('REJECT', 'LOG'))
        log_ = adm.get('log') or {}
        srv = adm.get('server') or {}
        return rejected > 0 and log_.get('count', 0) > 0 and srv.get('http_401', 0) > 0 and \
            srv.get('websocket_auth_failed', 0) > 0, {
                'guard_counters': counters, 'guard_log': log_, 'server_refusals': srv}

    def delete_step():
        out = {}
        for cid in list(state['created']):
            response, = call({'method': 'DELETE', 'path': f'/api/conversations/{cid}',
                              'timeout': 300})
            out[cid] = response.get('status')
            if _status_ok(response):
                state['created'].remove(cid)
        report = facts()
        view, ok = conversation_containers_view(profile, record, report)
        count, = call({'method': 'GET', 'path': '/api/conversations/count'})
        return not state['created'] and ok and view.get('count') == 0 and count.get('body') == 0, {
            'delete': out, 'containers_after': view.get('count'), 'count_after': count.get('body')}

    run('route inventory against the running server', inventory_step)
    run('unauthenticated and wrong-key requests to every route', sweep_step)
    run('trusted side with the key (positive control)', trusted_step)
    run('create two disposable conversations', create_step)
    run('agent network: listener, guest services, published ports, peer', network_step)
    run('agent network: session keys and start_child_conversation', custody_step)
    run('key check fails closed', keycheck_step)
    run('refusals logged', logged_step)
    run('delete the conversations', delete_step, always=bool(state['created']))
    out = {'schema': ADMISSION_PROBE_SCHEMA, 'operation': 'admission-probe',
           'labels': labels(profile), 'profile': profile['name'], 'instance': name,
           'conversations': conversations, 'started_at': started, 'ended_at': utc_now(),
           'seconds': round(time.time() - t0, 1),
           'result': 'PASS' if not failed and not stop_conditions else 'FAIL',
           'failed_steps': failed, 'stop_conditions': stop_conditions, 'steps': steps}
    out['record'] = write_record(idir, 'admission-probe', out)
    if out_file is not None:
        write_json_exclusive(out_file, json.loads(json.dumps(out, default=str)))
        out['out'] = str(out_file)
    return out


# ---------------------------------------------------------------- job daemon and management access (S-01.3.2)

JOB_PROBE_SCHEMA = 'ai-engineering-harness/profiles/job-access-probe-record/v1'
# The second disposable conversation of this probe (the fixture with this id).
JOB_PEER_CONVERSATION_ID = 'a0132b00-0000-4000-8000-000000000b02'
JOB_MARKER = 'AIEH-JOB-JSON '
JOB_CONNECT_S = 4               # one TCP or unix connect inside a container
JOB_SWEEP_DEADLINE_S = 240      # bounds the route sweep at one address if it stops refusing
JOB_SCAN_MAX_BYTES = 8 << 20    # files larger than this are counted, not read
GITEA_FINGERPRINT = re.compile(r'^sha256:[0-9a-f]{16}$')
# Where each inspected property of a job container comes from: the locked server's
# docker run (registry.py _build_container) or Moby's own default (the server passes
# nothing for it; daemon.json where noted).
JOB_PROPERTY_SOURCES = {
    'Config.User': 'server: --user <server uid>:<gid>',
    'HostConfig.CapDrop': 'server: --cap-drop ALL',
    'HostConfig.SecurityOpt': 'server: --security-opt no-new-privileges (daemon.json '
                              'no-new-privileges too)',
    'HostConfig.Ulimits': 'server: --ulimit core=0',
    'HostConfig.ExtraHosts': 'server: --add-host host.docker.internal:host-gateway',
    'HostConfig.PortBindings': 'server: -p 127.0.0.1::8000',
    'HostConfig.Binds': 'server: exactly three -v binds',
    'HostConfig.Memory/NanoCpus/PidsLimit': 'server: --memory, --cpus, --pids-limit (config)',
    'HostConfig.AutoRemove': 'server: --rm',
    'Config.EnvNames': 'server: -e for the forwarded names; the image for the rest',
    'HostConfig.Privileged': 'Moby default (no --privileged)',
    'HostConfig.CapAdd': 'Moby default (no --cap-add)',
    'AppArmorProfile': 'Moby default (docker-default, AppArmor enabled)',
    'seccomp': 'Moby default (the builtin profile; no seccomp option passed)',
    'HostConfig.IpcMode': 'Moby default (private)',
    'HostConfig.CgroupnsMode': 'Moby default (private on cgroup v2)',
    'HostConfig.PidMode/UTSMode/UsernsMode': 'Moby default (the container\'s own namespaces; '
                                             'no user-namespace remap)',
    'HostConfig.NetworkMode': 'Moby default (bridge: the server passes no --network)',
    'HostConfig.Devices/DeviceCgroupRules/GroupAdd/Sysctls': 'Moby default (none)',
    'HostConfig.ReadonlyRootfs': 'Moby default (false: the server passes no --read-only)',
    'HostConfig.Runtime': 'daemon.json default-runtime runc',
    'HostConfig.LogConfig': 'daemon.json log-driver json-file',
}

# Run inside a conversation container as its default user (python3, spec as base64 JSON):
# identity, capabilities, no_new_privs, seccomp, AppArmor; credential-like variable names of
# every readable process environment (names only); every socket file and every bound unix
# name; a connect to each declared engine socket and each socket found (a connected one is
# asked GET /_ping); whether sudo or su gives root.
JOB_ENV_PROBE = r'''import base64, errno, json, os, re, shutil, socket, stat, subprocess, sys
spec = json.loads(base64.b64decode(sys.argv[1]).decode('utf-8'))
pattern = re.compile(spec['pattern'], re.I)
keep = ('Uid', 'Gid', 'Groups', 'CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb', 'NoNewPrivs',
        'Seccomp')
def status(pid):
    try:
        lines = open('/proc/%s/status' % pid).read().splitlines()
    except OSError as exc:
        return {'error': type(exc).__name__}
    return {k: ' '.join(v.split()) for k, _, v in (l.partition(':') for l in lines) if k in keep}
def run(argv):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
        return {'rc': r.returncode, 'out': ' '.join((r.stdout + r.stderr).split())[:240]}
    except (OSError, subprocess.SubprocessError) as exc:
        return {'rc': None, 'out': type(exc).__name__}
out = {'id': run(['id'])['out'], 'self': status('self'), 'pid1': status('1')}
try:
    out['apparmor'] = open('/proc/self/attr/current').read().strip()
except OSError as exc:
    out['apparmor'] = type(exc).__name__
envs = {}
for d in sorted(os.listdir('/proc')):
    if not d.isdigit():
        continue
    try:
        data = open('/proc/%s/environ' % d, 'rb').read()
        comm = open('/proc/%s/comm' % d).read().strip()
    except OSError as exc:
        envs[d] = {'unreadable': type(exc).__name__}
        continue
    names = sorted({e.split(b'=', 1)[0].decode('latin-1') for e in data.split(bytes([0])) if e})
    envs[d] = {'comm': comm, 'names': [n for n in names if pattern.search(n)]}
    token = spec.get('attempt_token')
    if token:
        # D-6: of an attempt token's admitted name, only whether its value has the token's shape and
        # whether it has a provider key's; never the value
        shapes = {}
        for e in data.split(bytes([0])):
            name, sep, value = e.partition(b'=')
            name = name.decode('latin-1')
            if sep and name in token['names']:
                text = value.decode('latin-1')
                shapes[name] = {'token': re.fullmatch(token['token_shape'], text) is not None,
                                'provider_key': re.search(token['provider_key_shape'], text) is not None}
        if shapes:
            envs[d]['shapes'] = shapes
out['process_environments'] = envs
out['terminal_names'] = sorted(n for n in os.environ if pattern.search(n))
files, setuid = [], []
for root, dirs, names in os.walk('/', onerror=lambda e: None):
    if root in ('/proc', '/sys'):
        dirs[:] = []
        continue
    for name in names + dirs:
        p = os.path.join(root, name)
        try:
            st = os.lstat(p)
        except OSError:
            continue
        if stat.S_ISSOCK(st.st_mode):
            files.append(p)
        elif stat.S_ISREG(st.st_mode) and st.st_mode & 0o6000 and st.st_uid == 0:
            setuid.append(p)
out['socket_files'] = sorted(files)
out['setuid_root'] = sorted(setuid)
bound = []
for line in open('/proc/net/unix').read().splitlines()[1:]:
    parts = line.split()
    if len(parts) >= 8:
        bound.append(parts[7])
out['unix_bound'] = sorted(set(bound))
def connect(path):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(spec['timeout'])
    try:
        s.connect(('\0' + path[1:]) if path.startswith('@') else path)
    except socket.timeout:
        return {'outcome': 'timeout'}
    except OSError as exc:
        return {'outcome': errno.errorcode.get(exc.errno, str(exc.errno)) if exc.errno else type(exc).__name__}
    try:
        s.sendall(b'GET /_ping HTTP/1.0\r\nHost: docker\r\n\r\n')
        answer = s.recv(512).decode('latin-1')
    except OSError as exc:
        answer = type(exc).__name__
    finally:
        s.close()
    return {'outcome': 'connected', 'answer': ' '.join(answer.split())[:160],
            'docker_api': 'api-version' in answer.lower() or 'docker' in answer.lower()}
targets = list(spec['sockets']) + [p for p in out['socket_files'] + out['unix_bound']
                                  if p not in spec['sockets']]
out['connect'] = {p: connect(p) for p in targets}
out['sudo'] = run(['sudo', '-n', 'true']) if shutil.which('sudo') else None
out['su'] = run(['su', '-c', 'true', 'root']) if shutil.which('su') else None
print('AIEH-JOB-JSON ' + json.dumps(out, sort_keys=True))
'''

# Run inside a conversation container: every route of the inventory at each outer address,
# without a key and with the conversation's own inner key (read from /proc/1/environ inside
# the container, never sent from outside). Outcomes are counted; any HTTP or WebSocket
# answer is listed. spec: zlib-compressed base64 JSON {hosts, port, routes, timeout, deadline}.
JOB_ROUTE_SWEEP = r'''import base64, http.client, json, os, socket, sys, time, zlib
spec = json.loads(zlib.decompress(base64.b64decode(sys.argv[1])).decode('utf-8'))
key = ''
for e in open('/proc/1/environ', 'rb').read().split(bytes([0])):
    if e.startswith(b'OH_SESSION_API_KEYS_0='):
        key = e.split(b'=', 1)[1].decode('ascii')
def classify(exc):
    name = type(exc).__name__
    return {'ConnectionRefusedError': 'refused', 'ConnectionResetError': 'reset',
            'TimeoutError': 'timeout', 'timeout': 'timeout'}.get(name, name)
def attempt(host, method, path, headers):
    if method == 'WEBSOCKET':
        try:
            s = socket.create_connection((host, spec['port']), timeout=spec['timeout'])
        except OSError as exc:
            return classify(exc)
        try:
            req = 'GET %s HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n' % path
            req += 'Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n' % base64.b64encode(os.urandom(16)).decode()
            for k, v in headers.items():
                req += '%s: %s\r\n' % (k, v)
            s.sendall((req + '\r\n').encode())
            line = s.recv(256).split(b'\r\n')[0].decode('latin-1')
            return 'answered ' + line[:40]
        except OSError as exc:
            return 'after-connect ' + classify(exc)
        finally:
            s.close()
    conn = http.client.HTTPConnection(host, spec['port'], timeout=spec['timeout'])
    try:
        conn.request(method, path, headers=headers)
        return 'answered HTTP %s' % conn.getresponse().status
    except OSError as exc:
        return classify(exc)
    except http.client.HTTPException as exc:
        return 'after-connect ' + type(exc).__name__
    finally:
        conn.close()
out = {'inner_key_present': bool(key), 'hosts': {}}
for host in spec['hosts']:
    counts, answered, t0, n = {}, [], time.monotonic(), 0
    for method, path in spec['routes']:
        for variant, headers in (('no_key', {}), ('inner_key', {'X-Session-API-Key': key})):
            if time.monotonic() - t0 > spec['deadline']:
                outcome = 'not-attempted (deadline)'
            else:
                outcome = attempt(host, method, path, headers)
            n += 1
            counts[outcome] = counts.get(outcome, 0) + 1
            if outcome.startswith(('answered', 'after-connect')):
                answered.append([method, path, variant, outcome])
    out['hosts'][host] = {'attempts': n, 'outcomes': counts, 'answered': answered[:40],
                          'seconds': round(time.monotonic() - t0, 1)}
print('AIEH-JOB-JSON ' + json.dumps(out, sort_keys=True))
'''

# Run inside a conversation container: credentials by name and by fingerprint, never by
# value. Every readable process environment and command line and every readable regular
# file up to the size bound: each 43-character token is fingerprinted (aieh v1) and each
# 40-hex token hashed (Gitea's sha256 prefix); file names are matched against the credential
# file pattern. Control: the conversation's own session key is found in /proc/1/environ.
JOB_TOKEN_SCAN = r'''import base64, hashlib, json, os, re, stat, sys, time
spec = json.loads(base64.b64decode(sys.argv[1]).decode('utf-8'))
aieh, gitea = set(spec['aieh']), set(spec['gitea'])
names = re.compile(spec['files'])
T43 = re.compile(rb'(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{43}(?![A-Za-z0-9_-])')
H40 = re.compile(rb'(?<![0-9a-fA-F])[0-9a-f]{40}(?![0-9a-fA-F])')
NUL = bytes([0])
t0 = time.monotonic()
def fp(v):
    return hashlib.sha256(b'aieh-secret-fingerprint/v1\n' + v).hexdigest()
control = set()
for e in open('/proc/1/environ', 'rb').read().split(NUL):
    if e.startswith(b'OH_SESSION_API_KEYS_0='):
        control.add(fp(e.split(b'=', 1)[1]))
seen43, seen40, hits, control_hits = set(), set(), [], []
stats = {'files': 0, 'unreadable': 0, 'over_bound': 0, 'process_files': 0}
def scan(path, data):
    for m in T43.finditer(data):
        v = m.group(0)
        if v in seen43:
            continue
        seen43.add(v)
        f = fp(v)
        if f in aieh:
            hits.append([path, 'aieh:' + f])
        if f in control:
            control_hits.append(path)
    for m in H40.finditer(data):
        v = m.group(0)
        if v in seen40:
            continue
        seen40.add(v)
        f = 'sha256:' + hashlib.sha256(v).hexdigest()[:16]
        if f in gitea:
            hits.append([path, 'gitea:' + f])
for d in sorted(os.listdir('/proc')):
    if d.isdigit():
        for part in ('environ', 'cmdline'):
            try:
                data = open('/proc/%s/%s' % (d, part), 'rb').read()
            except OSError:
                stats['unreadable'] += 1
                continue
            stats['process_files'] += 1
            scan('/proc/%s/%s' % (d, part), data.replace(NUL, b'\n'))
named = []
for root, dirs, files in os.walk('/', onerror=lambda e: None):
    if root in ('/proc', '/sys', '/dev'):
        dirs[:] = []
        continue
    for n in files:
        p = os.path.join(root, n)
        try:
            st = os.lstat(p)
            if not stat.S_ISREG(st.st_mode):
                continue
            if names.search(n) or p.endswith('/.docker/config.json'):
                named.append(p)
            if st.st_size > spec['max_bytes']:
                stats['over_bound'] += 1
                continue
            with open(p, 'rb') as fh:
                data = fh.read()
        except OSError:
            stats['unreadable'] += 1
            continue
        stats['files'] += 1
        scan(p, data)
out = dict(stats, distinct_43=len(seen43), distinct_40hex=len(seen40), hits=hits,
           control_found=sorted(set(control_hits)), control_keys=len(control),
           credential_files=sorted(named), seconds=round(time.monotonic() - t0, 1))
print('AIEH-JOB-JSON ' + json.dumps(out, sort_keys=True))
'''


# Run inside a conversation container (S-01.4 egress sweep): one TCP connect or one UDP
# datagram per target, as the container's default user, with errno named. spec: base64 JSON
# {targets: [[proto, host, port, what]], timeout}. A UDP target gets a minimal DNS query; an
# ICMP port-unreachable surfaces as ECONNREFUSED on the connected socket.
JOB_EGRESS_SWEEP = r'''import base64, errno, json, socket, sys, time
spec = json.loads(base64.b64decode(sys.argv[1]).decode('utf-8'))
QUERY = bytes([0x41, 0x49, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 4]) + b'aieh' + bytes([7]) + \
    b'invalid' + bytes([0, 0, 1, 0, 1])
def name(exc):
    return errno.errorcode.get(exc.errno, str(exc.errno)) if exc.errno else type(exc).__name__
def attempt(proto, host, port):
    t0 = time.monotonic()
    kind = socket.SOCK_STREAM if proto == 'tcp' else socket.SOCK_DGRAM
    s = socket.socket(socket.AF_INET, kind)
    s.settimeout(spec['timeout'])
    try:
        s.connect((host, port))
        if proto == 'tcp':
            outcome = 'connected'
        else:
            s.send(QUERY)
            data = s.recv(512)
            outcome = 'answered %d bytes' % len(data)
    except socket.timeout:
        outcome = 'timeout'
    except OSError as exc:
        outcome = name(exc)
    finally:
        s.close()
    return {'outcome': outcome, 'seconds': round(time.monotonic() - t0, 2)}
out = {'results': []}
for proto, host, port, what in spec['targets']:
    out['results'].append(dict(attempt(proto, host, port), proto=proto, host=host, port=port,
                               what=what))
print('AIEH-JOB-JSON ' + json.dumps(out, sort_keys=True))
'''
# The S-01.4 decision rule, fixed before observation: the guard's reset or ICMP reject
# (ECONNREFUSED) is the only passing outcome; a timeout or an unreachable error alone is
# topology, not policy (FAIL); a connection or an answer is a stop condition.
EGRESS_REFUSED = 'ECONNREFUSED'
EGRESS_TOPOLOGY = frozenset({'timeout', 'ENETUNREACH', 'EHOSTUNREACH'})
EGRESS_GUARD_FAMILY = 'iptables'

# Run inside a conversation container of an instance with the inference composition (decision
# 0015 section 4.5): the inference endpoint without a token (one TCP connect and GET /, the
# status line only), the allow's edges and the container resolver (one TCP connect or one UDP
# datagram each, errno named), and one name lookup through the container's resolv.conf. spec:
# base64 JSON {endpoint: [host, port], targets: [[proto, host, port, what]], name, timeout}.
JOB_INFERENCE_SWEEP = r'''import base64, errno, json, socket, sys, time
spec = json.loads(base64.b64decode(sys.argv[1]).decode('utf-8'))
QUERY = bytes([0x41, 0x49, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 4]) + b'aieh' + bytes([7]) + \
    b'invalid' + bytes([0, 0, 1, 0, 1])
def name(exc):
    return errno.errorcode.get(exc.errno, str(exc.errno)) if exc.errno else type(exc).__name__
def attempt(proto, host, port):
    t0 = time.monotonic()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM if proto == 'tcp' else socket.SOCK_DGRAM)
    s.settimeout(spec['timeout'])
    try:
        s.connect((host, port))
        if proto == 'tcp':
            outcome = 'connected'
        else:
            s.send(QUERY)
            outcome = 'answered %d bytes' % len(s.recv(512))
    except socket.timeout:
        outcome = 'timeout'
    except OSError as exc:
        outcome = name(exc)
    finally:
        s.close()
    return {'outcome': outcome, 'seconds': round(time.monotonic() - t0, 2)}
def endpoint(host, port):
    t0 = time.monotonic()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(spec['timeout'])
    out = {'status': None}
    try:
        s.connect((host, port))
        s.sendall(('GET / HTTP/1.1\r\nHost: %s:%d\r\nConnection: close\r\n\r\n' % (host, port)).encode('ascii'))
        data = b''
        while b'\r\n' not in data and len(data) < 4096:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
        parts = data.split(b'\r\n', 1)[0].decode('latin-1').split(' ')
        out['status'] = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
        out['outcome'] = 'answered' if out['status'] is not None else 'connected'
    except socket.timeout:
        out['outcome'] = 'timeout'
    except OSError as exc:
        out['outcome'] = name(exc)
    finally:
        s.close()
    out['seconds'] = round(time.monotonic() - t0, 2)
    return out
def lookup(host):
    t0 = time.monotonic()
    try:
        socket.getaddrinfo(host, 443, socket.AF_UNSPEC, socket.SOCK_STREAM)
        out = {'outcome': 'resolved'}
    except socket.gaierror as exc:
        out = {'outcome': 'not-resolved', 'error': str(exc)[:200]}
    out['seconds'] = round(time.monotonic() - t0, 2)
    return out
host, port = spec['endpoint']
results = [dict(endpoint(host, port), proto='tcp', host=host, port=port,
                what='inference endpoint (no token)')]
for proto, h, p, what in spec['targets']:
    results.append(dict(attempt(proto, h, p), proto=proto, host=h, port=p, what=what))
results.append(dict(lookup(spec['name']), proto='dns', host=spec['name'], port=None,
                    what='name lookup'))
print('AIEH-JOB-JSON ' + json.dumps({'results': results}, sort_keys=True))
'''
INFERENCE_ENDPOINT_WHAT = 'inference endpoint (no token)'
# the guest's own login, outside every container (S-03.2 slice 3, nm-guest-inference): the
# container guard filters docker0 only, so while a forward is held the attempt token is the
# endpoint's only admission control for the guest's own processes
INFERENCE_GUEST_WHAT = 'inference endpoint from the guest login (no token)'
INFERENCE_LOOKUP_WHAT = 'name lookup'
INFERENCE_LOOKUP_NAME = 'deb.debian.org'
INFERENCE_JOB_STEP = 'inference endpoint, its edges and the resolver from inside each job ' \
                     '(decision 0015)'


def inference_job_spec(profile):
    """The predeclared inference sweep of a job (network.inference_composition.job_sweep)."""
    address, port = inference_endpoint(profile)
    sweep = inference_config(profile).get('job_sweep') or {}
    return {'endpoint': [address, port],
            'targets': [list(e) for e in sweep.get('edges') or []],
            'name': INFERENCE_LOOKUP_NAME, 'timeout': JOB_CONNECT_S}


def container_guard_rejects(report):
    """The container guard's IPv4 refusal packets (its REJECT rules) from on-demand facts."""
    adm = report.get('admission') if isinstance(report.get('admission'), dict) else {}
    rows = adm.get('iptables')
    if not isinstance(rows, list):
        return None
    return sum(r.get('packets', 0) for r in rows
               if isinstance(r, dict) and r.get('target') == 'REJECT')


def inference_job_verdict(results, before, after):
    """(ok, rows, stop, counters) of the inference sweep, by the rule fixed before observation:
    the endpoint answers 401 without a token (reachability and admission); every edge and
    resolver target is refused (ECONNREFUSED: the container guard's reset or ICMP reject); the
    name lookup returns no address; the guard's IPv4 REJECT counters rise by at least the
    refused attempts. A connection or an answer from an edge, or a resolved name, is a stop
    condition."""
    rows, stop, refused = [], [], 0
    for r in results:
        what, outcome = r.get('what'), r.get('outcome')
        if what == INFERENCE_ENDPOINT_WHAT:
            ok = outcome == 'answered' and r.get('status') == 401
        elif what == INFERENCE_GUEST_WHAT:
            ok = outcome == 'answered' and r.get('status') == 401 and \
                r.get('refusal') == 'TOKEN_MISSING'
            if outcome == 'answered' and r.get('status') != 401:
                stop.append({'condition': 'the inference endpoint admitted the guest login without '
                                          'a token', 'status': r.get('status')})
        elif what == INFERENCE_LOOKUP_WHAT:
            ok = outcome == 'not-resolved'
            if outcome == 'resolved':
                stop.append({'condition': 'a name resolved from a job', 'target': r.get('host'),
                             'conversation': r.get('conversation')})
        else:
            ok = outcome == EGRESS_REFUSED
            refused += 1 if ok else 0
            if outcome == 'connected' or str(outcome).startswith('answered'):
                stop.append({'condition': 'an edge of the inference allow was reached from a '
                                          'job', 'target': f"{r.get('proto')} {r.get('host')}:"
                                                           f"{r.get('port')}",
                             'conversation': r.get('conversation')})
        rows.append(dict(r, ok=ok))
    counters = {'before': before, 'after': after, 'refused': refused}
    counters['incremented'] = isinstance(before, int) and isinstance(after, int) and \
        after - before >= refused
    ok = bool(rows) and all(r['ok'] for r in rows) and counters['incremented'] and not stop
    return ok, rows, stop, counters


# Run inside the conversation container of the token's conversation (decision 0015 sections 3.3 and
# 4.4, S-03.2's proof): one request to the inference endpoint in the token family's route and auth
# header shape. The token arrives on standard input (a bash builtin's pipe, never an argument) and is
# never printed; the answer is reported by status, the broker's refusal code, its size and its sha256,
# and up to capture_max bytes it is returned whole (answer_b64) for S-03.2's provider-key search on
# the host, which takes it out of the result before anything is recorded.
# spec: base64 JSON {endpoint, method, path, header, scheme, body, with_token, timeout, max_bytes,
# capture_max}.
JOB_INFERENCE_TOKEN = r'''import base64, errno, hashlib, json, socket, sys, time
spec = json.loads(base64.b64decode(sys.argv[1]).decode('utf-8'))
token = sys.stdin.readline().strip() if spec['with_token'] else ''
host, port = spec['endpoint']
body = json.dumps(spec['body']).encode('utf-8')
head = ['%s %s HTTP/1.1' % (spec['method'], spec['path']), 'Host: %s:%d' % (host, port),
        'Content-Type: application/json', 'Content-Length: %d' % len(body), 'Connection: close']
if token:
    head.append('%s: %s' % (spec['header'], spec['scheme'] + ' ' + token if spec['scheme'] else token))
out = {'status': None, 'refusal': None}
t0 = time.monotonic()
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(spec['timeout'])
try:
    s.connect((host, port))
    s.sendall(('\r\n'.join(head) + '\r\n\r\n').encode('ascii') + body)
    data = b''
    while len(data) < spec['max_bytes']:
        chunk = s.recv(65536)
        if not chunk:
            break
        data += chunk
    if len(data) <= spec.get('capture_max', 0):
        out['answer_b64'] = base64.b64encode(data).decode('ascii')
    else:
        out['answer_omitted'] = len(data)
    top, _, payload = data.partition(b'\r\n\r\n')
    line = top.split(b'\r\n', 1)[0].decode('latin-1').split(' ')
    out['status'] = int(line[1]) if len(line) > 1 and line[1].isdigit() else None
    out['outcome'] = 'answered' if out['status'] is not None else 'connected'
    try:
        refusal = json.loads(payload.decode('utf-8')).get('aieh_refusal')
        out['refusal'] = refusal.get('code') if isinstance(refusal, dict) else None
    except (ValueError, AttributeError):
        pass
    out['body_bytes'] = len(payload)
    out['body_sha256'] = hashlib.sha256(payload).hexdigest()
    out['token_in_answer'] = bool(token) and token.encode('ascii') in data
except socket.timeout:
    out['outcome'] = 'timeout'
except OSError as exc:
    out['outcome'] = errno.errorcode.get(exc.errno, str(exc.errno)) if exc.errno else type(exc).__name__
finally:
    s.close()
out['seconds'] = round(time.monotonic() - t0, 2)
print('AIEH-JOB-JSON ' + json.dumps(out, sort_keys=True))
'''
INFERENCE_TOKEN_STEP = 'inference with the attempt token from inside its job: forwarded, refused ' \
                       'after revocation, refused without the forward (decision 0015)'
INFERENCE_REVOKE_STEP = 'revoke the attempt token at the probe\'s end (decision 0015 section 3.3)'
INFERENCE_REVOKER = 'tools/guest.py job-access-probe (the dispatcher\'s role during bootstrap)'
INFERENCE_PROBE_PROMPT = 'aieh S-03.2 inference-plane probe: no model'
INFERENCE_ANSWER_MAX = 1 << 20
INFERENCE_CAPTURE_MAX = 64 << 10
INFERENCE_KEY_SEARCH_STEP = 'the provider key itself in what crossed the forward to the job (synthetic ' \
                            'key, raw and encoded, S-03.2)'


def redact_secret(data, secret, label):
    """``data`` (JSON-shaped) with every occurrence of ``secret`` replaced by ``label``, and the
    number replaced under 'redactions': the last guard before a record is written."""
    text = json.dumps(data, default=str)
    count = text.count(secret)
    out = json.loads(text.replace(secret, label)) if count else json.loads(text)
    out['redactions'] = count
    return out


def read_attempt_token(stream):
    """One attempt token from ``stream`` (standard input, never argv), checked for its shape; the
    message of a refusal never repeats what was read."""
    text = stream.readline(512)
    token = text.strip() if isinstance(text, str) else ''
    ic = inference_control()
    try:
        ic.token_fingerprint(token)
    except ic.ControlError:
        raise Refused('REFUSED', '--attempt-token-stdin: standard input is not one attempt token '
                      '(aieh-inf- and 43 URL-safe characters)') from None
    return token


def container_python_sealed(script, arg, secret):
    """container_python, the secret on the script's standard input through bash's printf builtin
    (no process argument carries it)."""
    if not SEALED_SECRET.match(secret):
        raise Refused('REFUSED', 'the sealed secret is not one URL-safe word')
    return container_python(script, arg).replace(
        '&& python3 /tmp/aieh-job.py', f"&& printf '%s\\n' '{secret}' | python3 /tmp/aieh-job.py", 1)


def inference_token_spec(profile, family, model, with_token):
    """The in-container request of one family's first declared route (its method, path and auth
    header shape, as the broker's status reports the family), naming ``model``."""
    address, port = inference_endpoint(profile)
    method, path = sorted((r['method'], r['path']) for r in family['routes'])[0]
    return {'endpoint': [address, port], 'method': method, 'path': path,
            'header': family['auth']['header'], 'scheme': family['auth']['scheme'],
            'body': {'model': model, 'max_tokens': 16, 'stream': False,
                     'messages': [{'role': 'user', 'content': INFERENCE_PROBE_PROMPT}]},
            'with_token': with_token, 'timeout': JOB_CONNECT_S * 5, 'max_bytes': INFERENCE_ANSWER_MAX,
            'capture_max': INFERENCE_CAPTURE_MAX}


def inference_token_verdict(phases):
    """(ok, stop) of the token step's phases, by the rule fixed before observation: with the token
    the answer is the upstream's (2xx, no broker refusal); after revocation 401 TOKEN_REVOKED; without
    the forward ECONNREFUSED; after the forward is re-established 401 TOKEN_REVOKED again; the token
    never echoed. A revoked token answered 2xx, or a connection without the forward, is a stop
    condition."""
    stop, checks = [], {}
    forwarded, revoked = phases.get('forwarded') or {}, phases.get('after_revocation') or {}
    lost, back = phases.get('without_forward') or {}, phases.get('re_established') or {}
    checks['forwarded'] = forwarded.get('outcome') == 'answered' and \
        isinstance(forwarded.get('status'), int) and 200 <= forwarded['status'] < 300 and \
        forwarded.get('refusal') is None
    for name, got in (('after_revocation', revoked), ('re_established', back)):
        checks[name] = got.get('status') == 401 and got.get('refusal') == 'TOKEN_REVOKED'
        if isinstance(got.get('status'), int) and 200 <= got['status'] < 300:
            stop.append({'condition': 'a revoked attempt token was forwarded', 'phase': name})
    checks['without_forward'] = lost.get('outcome') == EGRESS_REFUSED
    if lost.get('outcome') in ('connected', 'answered'):
        stop.append({'condition': 'the endpoint answered while no forward session was held'})
    checks['revocation_answer'] = (phases.get('revocation') or {}).get('state') == 'revoked'
    checks['token_never_echoed'] = not any((p or {}).get('token_in_answer') for p in phases.values()
                                           if isinstance(p, dict))
    return all(checks.values()) and not stop, checks, stop


def egress_targets(record, jobs):
    """The predeclared egress sweep of a job (S-01.4): public literals, SLIRP's aliases (the
    host's loopback services and the resolver) and an unconfigured guestfwd-class address."""
    ports = record.get('ports') or {}
    host_ports = []
    for p in (jobs.get('host_alias') or {}).get('host_ports') or []:
        p = {'{ssh_port}': ports.get('ssh'), '{qmp_port}': ports.get('qmp')}.get(p, p)
        if isinstance(p, int):
            host_ports.append(p)
    targets = [['tcp', '1.1.1.1', 443, 'public literal'],
               ['tcp', '8.8.8.8', 53, 'public literal'],
               ['udp', '8.8.8.8', 53, 'public literal (the container resolver)']]
    targets += [['tcp', '10.0.2.2', p, 'SLIRP host-loopback alias (host service)']
                for p in host_ports]
    targets += [['tcp', '10.0.2.3', 53, 'SLIRP resolver alias'],
                ['udp', '10.0.2.3', 53, 'SLIRP resolver alias'],
                ['tcp', NETPROBE_GUESTFWD['addr'], NETPROBE_GUESTFWD['port'],
                 'unconfigured guestfwd-class address']]
    return targets


def egress_counters(report):
    """The egress guard's per-rule packet counters of one family (chain order: RETURN, LOG,
    REJECT tcp-reset, REJECT) and its log, from the on-demand facts."""
    adm = report.get('admission') if isinstance(report.get('admission'), dict) else {}
    egress = adm.get('egress') if isinstance(adm.get('egress'), dict) else {}
    rows = egress.get(EGRESS_GUARD_FAMILY)
    log_ = egress.get('log') if isinstance(egress.get('log'), dict) else {}
    if not isinstance(rows, list) or len(rows) != 4:
        return None, log_
    return [r.get('packets') if isinstance(r, dict) else None for r in rows], log_


EGRESS_NO_ROUTE_CLASS = 'topology (no route); the policy is proved by the route-present step'


def egress_verdict(results, before, after, off_link_judged=True):
    """(ok, rows, stop, counters) of the egress sweep under the S-01.4 decision rule. With
    ``off_link_judged`` false (the Overseer's fix-forward ruling), a public-literal target that
    the guest's routing answers (no route) is recorded as topology and left out of the
    verdict; the route-present step judges the policy for it."""
    rows, stop, refused = [], [], {'tcp': 0, 'udp': 0}
    for r in results:
        outcome = str(r.get('outcome'))
        off_link = str(r.get('what', '')).startswith('public literal')
        if outcome == EGRESS_REFUSED:
            klass = 'refused (reset or ICMP reject)'
            refused[r.get('proto')] = refused.get(r.get('proto'), 0) + 1
        elif outcome in EGRESS_TOPOLOGY and off_link and not off_link_judged:
            klass = EGRESS_NO_ROUTE_CLASS
        elif outcome in EGRESS_TOPOLOGY:
            klass = 'topology, not policy'
        elif outcome == 'connected' or outcome.startswith('answered'):
            klass = 'connection'
            stop.append({'condition': 'a job connected out of the guest', 'target': r})
        else:
            klass = 'other'
        rows.append(dict(r, verdict=klass))
    counters = {'before': before, 'after': after, 'refused_tcp': refused['tcp'],
                'refused_other': refused['udp']}
    counted = isinstance(before, list) and isinstance(after, list) and \
        all(isinstance(x, int) for x in before + after)
    if counted:
        delta = [a - b for a, b in zip(after, before)]
        counters['delta'] = {'RETURN': delta[0], 'LOG': delta[1], 'REJECT tcp-reset': delta[2],
                             'REJECT': delta[3]}
        counters['incremented'] = delta[2] >= refused['tcp'] and delta[3] >= refused['udp'] and \
            delta[2] + delta[3] > 0
        counters['exact'] = delta[2] == refused['tcp'] and delta[3] == refused['udp']
    else:
        counters['incremented'] = False
    ok = bool(rows) and all(r['verdict'].startswith('refused') or r['verdict'] == EGRESS_NO_ROUTE_CLASS
                            for r in rows) and counters['incremented'] and not stop
    return ok, rows, stop, counters


# The route-present falsification (S-01.4 fix-forward, the Overseer's ruling): a temporary
# IPv4 default route via SLIRP's gateway, added and always removed by the seeded root unit
# on agent's request files (create --provision --egress-falsification only).
EGRESS_ROUTE_GATEWAY = '10.0.2.2'
EGRESS_ROUTE_CEILING_S = 300
EGRESS_ROUTE_REQUEST = '/var/lib/aieh/facts-request/egress-route'
EGRESS_ROUTE_OFF = '/var/lib/aieh/facts-request/egress-route-off'
EGRESS_ROUTE_REPORT = '/run/aieh/egress-route.json'
EGRESS_ROUTE_WAIT_S = 60          # bounds a hang of the root unit (it answers in ~1 s)
EGRESS_ROUTE_TARGETS = [['tcp', '1.1.1.1', 443, 'public literal'],
                        ['tcp', '8.8.8.8', 53, 'public literal'],
                        ['udp', '8.8.8.8', 53, 'public literal (the container resolver)']]
EGRESS_ROUTE_CONTROL = [['tcp', '1.1.1.1', 443, 'guest namespace control (SLIRP alone)']]
# Run as agent: wait until the root unit's report has a serial above argv[2] and a state in
# argv[3] (comma-separated), or the ceiling argv[4]; print the report (or {}) as one line.
EGRESS_ROUTE_WAIT = r'''import json, sys, time
path, serial, states, ceiling = sys.argv[1], int(sys.argv[2]), sys.argv[3].split(','), float(sys.argv[4])
t0, report = time.monotonic(), {}
while True:
    try:
        report = json.load(open(path))
    except (OSError, ValueError):
        report = {}
    if int(report.get('serial', 0) or 0) > serial and report.get('state') in states:
        break
    if time.monotonic() - t0 > ceiling:
        report = dict(report, wait='ceiling reached')
        break
    time.sleep(0.2)
print(json.dumps(report, sort_keys=True))
'''


def egress_route_verdict(results, before, after, log_lines, uplink):
    """(ok, rows, stop, counters) of the route-present step under the decision rule fixed
    before the run: every container target refused with the guard's reset or ICMP reject,
    the guard's IPv4 REJECT counters up by exactly the attempts, and the LOG lines for the
    targets show OUT=<the guest uplink>. A timeout or ENETUNREACH is a FAIL; a connection is a
    stop condition."""
    rows, stop, attempts = [], [], {'tcp': 0, 'udp': 0}
    for r in results:
        outcome = str(r.get('outcome'))
        attempts[r.get('proto')] = attempts.get(r.get('proto'), 0) + 1
        if outcome == EGRESS_REFUSED:
            klass = 'refused (reset or ICMP reject)'
        elif outcome == 'connected' or outcome.startswith('answered'):
            klass = 'connection'
            stop.append({'condition': 'a job connected out of the guest with the route present',
                         'target': r})
        else:
            klass = 'not refused by the guard (FAIL)'
        rows.append(dict(r, verdict=klass))
    counters = {'before': before, 'after': after, 'attempts_tcp': attempts['tcp'],
                'attempts_other': attempts['udp']}
    counted = isinstance(before, list) and isinstance(after, list) and \
        all(isinstance(x, int) for x in before + after)
    if counted:
        delta = [a - b for a, b in zip(after, before)]
        counters['delta'] = {'RETURN': delta[0], 'LOG': delta[1], 'REJECT tcp-reset': delta[2],
                             'REJECT': delta[3]}
        counters['exact'] = delta[2] == attempts['tcp'] and delta[3] == attempts['udp']
    else:
        counters['exact'] = False
    hosts = {r.get('host') for r in results}
    logged = [line for line in log_lines or []
              if any(f'DST={h} ' in line for h in hosts)]
    counters['log_lines'] = logged
    counters['log_out_uplink'] = bool(logged) and bool(uplink) and \
        all(f' OUT={uplink} ' in line for line in logged)
    ok = bool(rows) and all(r['verdict'].startswith('refused') for r in rows) and \
        counters['exact'] and counters['log_out_uplink'] and not stop
    return ok, rows, stop, counters


def _job_json(stdout):
    """The last AIEH-JOB-JSON line of a container script's output."""
    lines = [line for line in (stdout or '').splitlines() if line.startswith(JOB_MARKER)]
    if not lines:
        raise Refused('CONTAINER', f'the container script printed no result: {(stdout or "")[-300:]}')
    return json.loads(lines[-1][len(JOB_MARKER):])


def container_python(script, arg):
    """A bash command that runs ``script`` with python3 in the container, the script and its
    one argument as base64 (no quoting, no secret on the command line)."""
    return (f"echo {base64.b64encode(script.encode('utf-8')).decode('ascii')} | base64 -d > "
            f"/tmp/aieh-job.py && python3 /tmp/aieh-job.py {arg}; rc=$?; rm -f /tmp/aieh-job.py; "
            "exit $rc")


def parse_token_fingerprints(values):
    """``--token-fingerprint LABEL=sha256:<16 hex>`` values (Gitea's token fingerprint form,
    S-01.2.2) as {label: fingerprint}."""
    out = {}
    for value in values or []:
        label, sep, fp = str(value).partition('=')
        if not sep or not re.match(r'^[A-Za-z0-9_.:-]{1,64}$', label) or \
                not GITEA_FINGERPRINT.match(fp):
            raise Refused('REFUSED', f'--token-fingerprint {value!r}: LABEL=sha256:<16 hex digits>')
        out[label] = fp
    return out


def attempt_token_environment(profile, record):
    """D-6: the admitted names of a broker attempt token in a job's process environments
    (network.inference_composition.attempt_token_environment.names), for an instance created
    with the inference composition only; () otherwise, so a guest without it keeps the job
    contract exactly (jobs.environment.secret_names)."""
    if not inference_opted(record):
        return ()
    block = inference_config(profile).get('attempt_token_environment')
    names = block.get('names') if isinstance(block, dict) else None
    if not isinstance(names, list) or not all(isinstance(n, str) and n for n in names):
        return ()
    return tuple(names)


def attempt_token_spec(names):
    """The job environment probe's attempt_token entry: the admitted names, the broker's token
    shape and the provider-key shapes the qualification create refuses (acp_qualification)."""
    acp = acp_qualification()
    return {'names': list(names), 'token_shape': acp.broker.TOKEN_SHAPE.pattern,
            'provider_key_shape': acp.PROVIDER_KEY_SHAPE.pattern}


def attempt_token_admission(data, names):
    """{pid: [name]} of the admitted names whose value had the attempt token's shape and no
    provider key's ('admitted'), of those that did not ('not_token'), and of those holding a
    provider key's shape ('provider_key'), from a job environment probe's process
    environments (shapes only, never a value)."""
    out = {'admitted': {}, 'not_token': {}, 'provider_key': {}}
    for pid, entry in sorted((data.get('process_environments') or {}).items()):
        shapes = entry.get('shapes') if isinstance(entry.get('shapes'), dict) else {}
        for name in sorted(set(entry.get('names') or []) & set(names)):
            shape = shapes.get(name) if isinstance(shapes.get(name), dict) else {}
            if shape.get('provider_key') is not False:
                if shape.get('provider_key') is True:
                    out['provider_key'].setdefault(pid, []).append(name)
                else:
                    out['not_token'].setdefault(pid, []).append(name)
            elif shape.get('token') is True:
                out['admitted'].setdefault(pid, []).append(name)
            else:
                out['not_token'].setdefault(pid, []).append(name)
    return out


def job_env_verdict(profile, server_user, data, attempt_token_names=()):
    """The in-container view of one job against provisioning.agent_server.jobs.process and
    .environment: (ok, problems, root_obtainable). ``attempt_token_names`` (D-6; only for the
    conversation whose admitted create carries a broker attempt token, on a guest with the
    inference composition, attempt_token_environment): those names are admitted in a
    process environment too, each only where its value had the broker's token shape and no
    provider key's shape (the probe reports the shapes, never the value)."""
    jobs = jobs_config(profile)
    proc, env = jobs.get('process') or {}, jobs.get('environment') or {}
    secret_names = set(env.get('secret_names') or [])
    admitted = attempt_token_admission(data, attempt_token_names)['admitted'] if attempt_token_names else {}
    problems = []
    me = data.get('self') or {}
    uid, gid = str(server_user.get('uid')), str(server_user.get('gid'))
    if (me.get('Uid') or '').split() != [uid] * 4 or (me.get('Gid') or '').split() != [gid] * 4 or \
            (me.get('Groups') or '').split() != [gid]:
        problems.append({'check': 'identity: the server user, no supplementary group',
                         'observed': {k: me.get(k) for k in ('Uid', 'Gid', 'Groups')}})
    for who in ('self', 'pid1'):
        st = data.get(who) or {}
        caps = {k: st.get(k) for k in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb')}
        if any(v != proc.get('capabilities') for v in caps.values()) or \
                st.get('NoNewPrivs') != proc.get('no_new_privs') or \
                st.get('Seccomp') != proc.get('seccomp'):
            problems.append({'check': f'{who}: no capability, no_new_privs, seccomp filter',
                             'observed': st})
    if data.get('apparmor') != proc.get('apparmor'):
        problems.append({'check': 'AppArmor profile', 'observed': data.get('apparmor')})
    if data.get('terminal_names'):
        problems.append({'check': 'terminal environment: no credential or engine name',
                         'observed': data.get('terminal_names')})
    extra = {pid: e.get('names') for pid, e in (data.get('process_environments') or {}).items()
             if set(e.get('names') or []) - secret_names - set(admitted.get(pid) or [])}
    if extra:
        problems.append({'check': 'process environments: only the conversation keys',
                         'observed': extra})
    root = any(isinstance(r, dict) and r.get('rc') == 0 for r in (data.get('sudo'), data.get('su')))
    return not problems, problems, root


def job_socket_verdict(profile, data, uid):
    """The engine socket attempts of one job: (ok, rows, stop). Every declared path must be
    absent; a socket found in the container may refuse or be absent too; a connection that
    answers the Docker API is a stop condition."""
    declared = [str(p).replace('{uid}', str(uid)) for p in jobs_config(profile).get('engine_sockets') or []]
    rows, ok, stop = [], True, []
    for path, got in sorted((data.get('connect') or {}).items()):
        outcome = (got or {}).get('outcome')
        want = ['ENOENT'] if path in declared else ['ENOENT', 'ECONNREFUSED', 'EACCES']
        good = outcome in want
        ok = ok and good
        rows.append({'path': path, 'declared': path in declared, 'expected': want,
                     'observed': outcome, 'answer': (got or {}).get('answer'), 'ok': good})
        if outcome == 'connected' and ((got or {}).get('docker_api') or path in declared):
            stop.append({'condition': 'an engine socket answered from a job', 'socket': rows[-1]})
    missing = [p for p in declared if p not in (data.get('connect') or {})]
    if missing:
        ok = False
        rows.append({'missing_attempts': missing})
    return ok, rows, stop


class ForwardControl:
    """The token step's hold on the instance's forward session: status, stop and start (decision
    0015 section 4.4), through inference-forward."""

    def __init__(self, ctx, name, access):
        self.ctx, self.name, self.access = ctx, name, access

    def status(self):
        return forward_state(self.ctx.profile, self.ctx.instance_dir(self.name))

    def stop(self):
        return inference_forward(self.ctx, self.name, 'stop')

    def start(self):
        return inference_forward(self.ctx, self.name, 'start', broker=self.access)


def job_access_probe(ctx, name, out_path=None, token_fingerprints=None, channels=None,
                     ssh_fn=None, attempt_token=None, broker=None, forward=None,
                     provider_key=None):
    """job-access-probe (S-01.3.2) on a running provisioned instance: from inside two
    disposable conversation containers (the job environment; the agent's own terminal,
    through the outer server's proxied bash route), the job's effective environment (docker
    inspect from the root facts, and its own view: identity, capabilities, no_new_privs,
    seccomp, AppArmor, credential-like variable names, sockets, root), every engine socket,
    the engine API over TCP and the host aliases at every address, every privileged route of
    the outer server at every address, and the management, Owner, admin and bot credentials
    by name and fingerprint; the trusted side with the key, the inner server and the
    hardening controls as positive controls. One machine verdict, PASS or FAIL; an engine
    socket or API, a management route or a host service reachable from a job is a stop
    condition. ``channels(record) -> (api, facts)`` and ``ssh_fn(record)`` stand in for the
    guest in tests.

    ``attempt_token`` (decision 0015, an instance with the inference composition only): an attempt
    token the broker issued for one of the probe's conversations, read from standard input by the
    command line. From inside that conversation's container the probe shows it forwarded to the
    family's upstream, refused at once after the probe revokes it, refused (ECONNREFUSED) while the
    forward session is stopped, and refused again after the forward is re-established; at the end
    the token is revoked if it is not yet. It travels only sealed (in a script's text on standard
    input); records carry its fingerprint only. ``broker`` and ``forward`` stand in for the broker's
    control listener and the forward session in tests.

    ``provider_key`` (S-03.2, with ``attempt_token`` only): the synthetic qualification key the
    broker was started with, read from standard input after the token. Every answer the job (and
    the guest login) received from the endpoint comes back whole (up to INFERENCE_CAPTURE_MAX) and
    is searched on the host, in memory, for the key itself, raw and encoded
    (forward_answers_search); the answers are never recorded, the record carries counts only, and
    a record that would hold the key is not written. The key never travels to the guest."""
    idir = ctx.instance_dir(name)
    _, record = running_instance(ctx, name)
    if not record.get('provisioning'):
        raise Refused('REFUSED', f'{name} was not created with --provision; it runs no Agent Server')
    token_fp = None
    if provider_key is not None and attempt_token is None:
        raise Refused('REFUSED', '--provider-key-stdin needs --attempt-token-stdin: the key is searched '
                      'for in the answers the token step receives')
    if attempt_token is not None:
        if not inference_opted(record):
            raise Refused('REFUSED', f'{name} was not created with create --provision --inference: '
                          'an attempt token has no endpoint to reach')
        ic = inference_control()
        try:
            token_fp = ic.token_fingerprint(attempt_token)
        except ic.ControlError:
            raise Refused('REFUSED', 'the attempt token is not of the broker\'s shape') from None
        broker = broker or BrokerAccess()
        forward = forward or ForwardControl(ctx, name, broker)
    jobs = jobs_config(ctx.profile)
    adm = admission_config(ctx.profile)
    if not jobs or not adm:
        raise Refused('REFUSED', 'the profile declares no provisioning.agent_server.jobs and '
                      'admission')
    gitea = parse_token_fingerprints(token_fingerprints)
    out_file = None
    if out_path:
        out_file = Path(out_path).resolve()
        if os.path.lexists(out_file) or not out_file.parent.is_dir() or \
                inside(out_file, ctx.repo) or inside(out_file, idir):
            raise Refused('REFUSED', f'--out {out_path}: must be a new file in an existing '
                          'directory, outside the checkout and the instance directory')
    profile = ctx.profile
    server = provisioning_config(profile)['agent_server']
    listener = server['listener']
    routes, inventory_problems = load_routes(ctx)
    body_a, fixture_problems, _ = _fixture(ctx)
    body_b = dict(body_a, conversation_id=JOB_PEER_CONVERSATION_ID,
                  tags={'aieh': 's-01.3.2-disposable-peer'})
    conversations = [body_a['conversation_id'], JOB_PEER_CONVERSATION_ID]

    def default_channels(rec):
        ssh = Ssh(profile, idir, rec['ports']['ssh'])
        return GuestApi(ssh, profile), GuestFacts(ssh, profile)
    channels = channels or default_channels
    ssh = (ssh_fn or (lambda rec: Ssh(profile, idir, rec['ports']['ssh'])))(record)
    api, facts = channels(record)
    t0, started = time.time(), utc_now()
    steps, failed, stop_conditions = [], [], []
    state = {'created': []}
    memo = {}
    answers = []          # (label, bytes): what the endpoint answered in the guest, in memory only
    caught = (Refused, OSError, ValueError, KeyError, TypeError, IndexError,
              subprocess.SubprocessError)

    def run(step, func, always=False):
        if (failed or stop_conditions) and not always:
            steps.append({'step': step, 'skipped': 'an earlier step failed'})
            return None
        s = time.time()
        entry = {'step': step, 'started_at': utc_now()}
        try:
            ok, detail = func()
        except caught as exc:
            ok, detail = False, {'error': getattr(exc, 'code', type(exc).__name__),
                                 'message': str(exc), 'detail': getattr(exc, 'detail', None)}
        entry.update(seconds=round(time.time() - s, 1), ok=bool(ok), detail=detail)
        steps.append(entry)
        log(f'job-access-probe: {step}: {"ok" if ok else "FAILED"} ({entry["seconds"]} s)')
        if not ok:
            failed.append(step)
        return detail

    def call(*requests, secret=None):
        data = api(list(requests), secret=secret) if secret else api(list(requests))
        if data.get('session_key_occurrences'):
            raise Refused('SECRET', 'a response carried the session key '
                          f'({data["session_key_occurrences"]} occurrence(s), redacted)')
        if secret:
            memo['token_echoes'] = memo.get('token_echoes', 0) + \
                int(data.get('sealed_occurrences') or 0)
        return data['responses']

    def in_container(conversation, command, timeout=300, secret=None):
        response, = call({'method': 'POST',
                          'path': f'/api/conversations/{conversation}/bash/execute_bash_command',
                          'json': {'command': command, 'cwd': '/workspace', 'timeout': timeout},
                          'timeout': timeout + 60}, secret=secret)
        body = response.get('body') if isinstance(response.get('body'), dict) else {}
        if not _status_ok(response) or body.get('exit_code') is None:
            raise Refused('CONTAINER', f'the command did not run in {conversation}: '
                          f'{json.dumps(response)[:400]}')
        return body.get('stdout') or ''

    def boot_facts():
        result = ssh.run(['python3', '-', provisioning_config(profile)['facts']['path']],
                         input_text='import json,sys\nprint(json.dumps(json.load(open(sys.argv[1]))))\n',
                         timeout=120)
        try:
            return json.loads(result.stdout.strip().splitlines()[-1])
        except (IndexError, ValueError):
            raise Refused('PROBE', f'no boot facts (rc {result.returncode})')

    def addresses():
        result = ssh.run(['ip', '-o', '-4', 'address', 'show'], timeout=60)
        addrs = []
        for line in result.stdout.splitlines():
            parts = line.split()
            if 'inet' in parts:
                addr = parts[parts.index('inet') + 1].split('/')[0]
                if not addr.startswith('127.'):
                    addrs.append(addr)
        return sorted(addrs)

    def trusted_step():
        count, info = call({'method': 'GET', 'path': '/api/conversations/count'},
                           {'method': 'GET', 'path': '/server_info', 'auth': False})
        return _status_ok(count) and _status_ok(info) and count.get('body') == 0, {
            'count': {'status': count.get('status'), 'body': count.get('body')},
            'server_info': {'status': info.get('status')}}

    def create_step():
        out = {}
        for body in (body_a, body_b):
            response, = call({'method': 'POST', 'path': '/api/conversations', 'json': body,
                              'timeout': 600})
            out[body['conversation_id']] = {'status': response.get('status'),
                                            'seconds': response.get('seconds')}
            if not _status_ok(response):
                stop_conditions.append({'condition': 'create returned non-2xx (a refusal)',
                                        'response': response})
                return False, out
            state['created'].append(body['conversation_id'])
        return not fixture_problems and not inventory_problems, {
            'create': out, 'fixture_problems': fixture_problems,
            'inventory_problems': inventory_problems}

    def inspected_step():
        report = facts()
        memo['server_user'] = report.get('server_user') or {}
        view, ok = conversation_containers_view(profile, record, report)
        allowance = listener_allowance(profile, report)
        memo['published'] = sorted({str(a.get('local', '')).rpartition(':')[2]
                                    for a in allowance.get('allowed') or [] if a.get('local')})
        keys = [k for k in (jobs.get('host_config') or {}) if k not in ('rule', 'AppArmorProfile')]
        effective = []
        for c in report.get('containers') or []:
            host = c.get('HostConfig') or {}
            effective.append({
                'id': str(c.get('Id'))[:12], 'conversation': conversation_hex(c),
                'AppArmorProfile': c.get('AppArmorProfile'),
                'Config.User': (c.get('Config') or {}).get('User'),
                'Config.EnvNames': (c.get('Config') or {}).get('EnvNames'),
                'HostConfig': {k: host.get(k) for k in keys + [
                    'ExtraHosts', 'NetworkMode', 'ReadonlyRootfs', 'Ulimits', 'Runtime',
                    'PortBindings', 'Binds', 'Memory', 'NanoCpus', 'PidsLimit', 'AutoRemove']},
                'Mounts': [list(m) for m in effective_container_mounts(c)]})
        return ok and view.get('count') == 2 and not allowance['violations'], {
            'containers': view, 'allowance': allowance, 'effective': effective,
            'sources': JOB_PROPERTY_SOURCES}

    def env_step():
        user = memo.get('server_user') or {}
        spec = {'pattern': (jobs.get('environment') or {}).get('credential_name_pattern'),
                'sockets': [str(p).replace('{uid}', str(user.get('uid')))
                            for p in jobs.get('engine_sockets') or []],
                'timeout': JOB_CONNECT_S}
        arg = base64.b64encode(json.dumps(spec).encode('utf-8')).decode('ascii')
        results, ok_all = {}, True
        for cid in conversations:
            data = _job_json(in_container(cid, container_python(JOB_ENV_PROBE, arg), 300))
            ok, problems, root = job_env_verdict(profile, user, data)
            entry = {'default_user': data, 'problems': problems, 'root_obtainable': root}
            if root:
                # repeat the socket attempts as root (sudo -n), as the dispatch requires
                command = container_python(JOB_ENV_PROBE, arg).replace(
                    'python3 /tmp/aieh-job.py', 'sudo -n python3 /tmp/aieh-job.py')
                entry['root'] = _job_json(in_container(cid, command, 300))
            results[cid] = entry
            ok_all = ok_all and ok
        memo['env'] = results
        return ok_all, {cid: {k: v for k, v in e.items() if k != 'default_user'} |
                        {'identity': e['default_user'].get('id'),
                         'status': e['default_user'].get('self'),
                         'pid1_status': e['default_user'].get('pid1'),
                         'apparmor': e['default_user'].get('apparmor'),
                         'process_environments': e['default_user'].get('process_environments'),
                         'terminal_names': e['default_user'].get('terminal_names'),
                         'setuid_root': e['default_user'].get('setuid_root'),
                         'sudo': e['default_user'].get('sudo'), 'su': e['default_user'].get('su')}
                        for cid, e in results.items()}

    def socket_step():
        uid = (memo.get('server_user') or {}).get('uid')
        out, ok_all = {}, True
        for cid, entry in (memo.get('env') or {}).items():
            per = {}
            for who in ('default_user', 'root'):
                if who not in entry:
                    continue
                ok, rows, stop = job_socket_verdict(profile, entry[who], uid)
                stop_conditions.extend(dict(s, conversation=cid, user=who) for s in stop)
                ok_all = ok_all and ok
                per[who] = {'socket_files': entry[who].get('socket_files'),
                            'unix_bound': entry[who].get('unix_bound'), 'attempts': rows}
            out[cid] = per
        return ok_all and len(out) == 2, out

    def tcp_step():
        guest_addrs = addresses()
        memo['guest_addresses'] = guest_addrs
        ports = record.get('ports') or {}
        alias = jobs.get('host_alias') or {}
        host_ports = []
        for p in alias.get('host_ports') or []:
            p = {'{ssh_port}': ports.get('ssh'), '{qmp_port}': ports.get('qmp')}.get(p, p)
            if isinstance(p, int):
                host_ports.append(p)
        engine = [int(p) for p in jobs.get('engine_tcp_ports') or []]
        published = [int(p) for p in memo.get('published') or []]
        ips = {cid: (in_container(cid, 'hostname -I', 30).split() or [None])[0]
               for cid in conversations}
        results, ok_all = {}, True
        for cid in conversations:
            peer = ips[conversations[1 - conversations.index(cid)]]
            targets = []                                  # (host, port, what, allowed, stop kind)
            for host in ['host.docker.internal'] + guest_addrs:
                for port in engine:
                    targets.append((host, port, 'engine API (guest)', {'refused'}, 'engine'))
                targets.append((host, listener['port'], 'management listener', {'refused'},
                                'listener'))
                for port in published:
                    targets.append((host, port, 'published conversation port', {'refused'}, None))
            for port in engine:
                targets.append(('127.0.0.1', port, 'engine API (own loopback)', {'refused'},
                                'engine'))
            for host in alias.get('addresses') or []:
                for port in engine:
                    targets.append((host, port, 'engine API (SLIRP alias)', {'refused'}, 'engine'))
                if host == '10.0.2.2':
                    for port in host_ports:
                        targets.append((host, port, 'host loopback service (SLIRP alias)',
                                        {'refused'}, 'host'))
            for port in engine:
                targets.append((peer, port, 'engine API (peer container)',
                                {'timeout', 'unreachable'}, 'engine'))
            targets.append(('127.0.0.1', 8000, 'own inner server (control)', {'connected'}, None))
            spec = ' '.join(f'{h}:{p}' for h, p, _, _, _ in targets)
            text = in_container(cid, f'TARGETS="{spec}"\n' + CONTAINER_NET_PROBE, 600)
            parsed = parse_net_probe(text)
            rows = []
            for host, port, what, allowed, kind in targets:
                got = parsed.get(f'{host}:{port}') or {'outcome': 'missing'}
                good = got['outcome'] in allowed
                if what.endswith('(control)'):
                    good = good and str(got.get('answer', '')).startswith('HTTP/1.1 200')
                ok_all = ok_all and good
                rows.append({'target': f'{host}:{port}', 'what': what, 'expected': sorted(allowed),
                             'observed': got['outcome'], 'answer': got.get('answer'), 'ok': good})
                if kind and got['outcome'] == 'connected':
                    stop_conditions.append({'condition': f'a {kind} endpoint answered from a job',
                                            'conversation': cid, 'target': rows[-1]})
            results[cid] = {'container_address': ips[cid],
                            'host.docker.internal': (_probe_lines(text, 'HOSTS_HDI') or [''])[0],
                            'identity': (_probe_lines(text, 'ID') or [''])[0], 'targets': rows}
        return ok_all, {'guest_addresses': guest_addrs, 'published_ports': published,
                        'host_ports': host_ports, 'containers': results}

    def routes_step():
        hosts = ['host.docker.internal'] + (memo.get('guest_addresses') or addresses())
        attempts = [[r['method'], concrete_path(r['path'])] for r in routes['routes']]
        spec = {'hosts': hosts, 'port': listener['port'], 'routes': attempts,
                'timeout': JOB_CONNECT_S, 'deadline': JOB_SWEEP_DEADLINE_S}
        arg = base64.b64encode(zlib.compress(json.dumps(spec).encode('utf-8'), 9)).decode('ascii')
        out, ok_all = {}, True
        for cid in conversations:
            data = _job_json(in_container(cid, container_python(JOB_ROUTE_SWEEP, arg), 1800))
            for host, h in (data.get('hosts') or {}).items():
                if h.get('answered'):
                    stop_conditions.append({'condition': 'the management listener answered '
                                            'from a job', 'conversation': cid, 'host': host,
                                            'answered': h['answered'][:5]})
            good = data.get('inner_key_present') is True and \
                sorted(data.get('hosts') or {}) == sorted(hosts) and \
                all(set(h.get('outcomes') or {}) == {'refused'} and
                    h.get('attempts') == 2 * len(attempts) for h in (data.get('hosts') or {}).values())
            ok_all = ok_all and good
            out[cid] = dict(data, ok=good)
        return ok_all, {'routes': len(attempts), 'variants': ['no_key', 'inner_key'],
                        'port': listener['port'], 'containers': out}

    def token_step():
        boot = boot_facts()
        memo['boot'] = boot
        outer = ((boot.get('agent_server') or {}).get('secrets') or {}).get('fingerprints') or {}
        spec = {'aieh': sorted(outer.values()), 'gitea': sorted(gitea.values()),
                'files': jobs.get('credential_files'), 'max_bytes': JOB_SCAN_MAX_BYTES}
        arg = base64.b64encode(json.dumps(spec).encode('utf-8')).decode('ascii')
        label_of = {v: f'aieh:{k}' for k, v in outer.items()}
        label_of.update({v: f'gitea:{k}' for k, v in gitea.items()})
        out, ok_all = {}, len(outer) == 2
        for cid in conversations:
            data = _job_json(in_container(cid, container_python(JOB_TOKEN_SCAN, arg), 1800))
            hits = [[p, label_of.get(f.split(':', 1)[1], f)] for p, f in data.get('hits') or []]
            good = not data.get('hits') and not data.get('credential_files') and \
                bool(data.get('control_found')) and data.get('files', 0) > 0
            ok_all = ok_all and good
            out[cid] = dict(data, hits=hits, ok=good)
        return ok_all, {'searched': {'outer (aieh v1)': sorted(outer),
                                     'gitea (sha256 prefix)': sorted(gitea)},
                        'size_bound_bytes': JOB_SCAN_MAX_BYTES, 'containers': out}

    def controls_step():
        boot = memo.get('boot') or boot_facts()
        moby = provisioning_config(profile).get('moby') or {}
        daemon = boot.get('daemon_json') if isinstance(boot.get('daemon_json'), dict) else {}
        info = boot.get('info') if isinstance(boot.get('info'), dict) else {}
        security = info.get('SecurityOptions') if isinstance(info.get('SecurityOptions'), list) else []
        adm_facts = boot.get('admission') if isinstance(boot.get('admission'), dict) else {}
        unit = adm_facts.get('guard_unit') if isinstance(adm_facts.get('guard_unit'), dict) else {}
        keycheck = adm_facts.get('keycheck') if isinstance(adm_facts.get('keycheck'), dict) else {}
        observed = {'daemon.json no-new-privileges': daemon.get('no-new-privileges'),
                    'daemon.json icc': daemon.get('icc'),
                    'daemon.json hosts': daemon.get('hosts'),
                    'SecurityOptions': security,
                    'guard unit': unit.get('ActiveState'),
                    'docker.service requires the guard': adm_facts.get('docker_requires_guard'),
                    'key check ExecStartPre': keycheck.get('exec_start_pre')}
        ok = daemon.get('no-new-privileges') is True and daemon.get('icc') is False and \
            'hosts' not in daemon and \
            set(moby.get('required_security_options') or []) <= set(security) and \
            unit.get('ActiveState') == 'active' and adm_facts.get('docker_requires_guard') is True \
            and keycheck.get('exec_start_pre') is True
        return ok, {'declared': {'daemon.json no-new-privileges': True, 'daemon.json icc': False,
                                 'daemon.json hosts': None,
                                 'SecurityOptions': f"including {moby.get('required_security_options')}",
                                 'guard unit': 'active',
                                 'docker.service requires the guard': True,
                                 'key check ExecStartPre': True},
                    'observed': observed}

    def egress_step():
        """S-01.4: the predeclared egress sweep from inside each job, the egress guard's
        counters read before and after (on-demand root facts), judged by the decision rule
        fixed before observation."""
        targets = egress_targets(record, jobs)
        spec = {'targets': targets, 'timeout': JOB_CONNECT_S}
        arg = base64.b64encode(json.dumps(spec).encode('utf-8')).decode('ascii')
        before, log_before = egress_counters(facts())
        results = []
        for cid in conversations:
            data = _job_json(in_container(cid, container_python(JOB_EGRESS_SWEEP, arg), 300))
            results += [dict(r, conversation=cid) for r in data.get('results') or []]
        after, log_after = egress_counters(facts())
        ok, rows, stop, counters = egress_verdict(results, before, after, off_link_judged=False)
        stop_conditions.extend(stop)
        complete = len(results) == len(targets) * len(conversations)
        return ok and complete, {
            'decision_rule': 'PASS: every target refused with the guard\'s reset or ICMP reject '
                             '(ECONNREFUSED) and the guard\'s REJECT counters incremented; FAIL: a '
                             'timeout or an unreachable error alone (topology, not policy); STOP: '
                             'any connection. Off-link public literals without a route are '
                             'recorded as ' + EGRESS_NO_ROUTE_CLASS + ' and left out of the '
                             'verdict (Overseer ruling, S-01.4 fix-forward)',
            'targets': targets, 'results': rows, 'counters': counters,
            'guard_log': {'count_before': log_before.get('count'),
                          'count_after': log_after.get('count'),
                          'tail': (log_after.get('tail') or [])[-16:]}}

    def route_report(serial, states, ceiling=EGRESS_ROUTE_WAIT_S):
        result = ssh.run(['python3', '-', EGRESS_ROUTE_REPORT, str(serial), ','.join(states),
                          str(ceiling)], input_text=EGRESS_ROUTE_WAIT, timeout=ceiling + 60)
        try:
            return json.loads(result.stdout.strip().splitlines()[-1])
        except (IndexError, ValueError):
            return {'wait': f'no report (rc {result.returncode})'}

    def ipv4_routes():
        result = ssh.run(['ip', '-4', 'route', 'show'], timeout=60)
        return result.stdout.strip().splitlines()

    def route_step():
        """S-01.4 fix-forward (the Overseer's ruling): with a temporary IPv4 default route via
        SLIRP's gateway in the guest (added by the seeded root unit on agent's request), sweep
        the off-link targets from both jobs and once from the guest's own namespace (a
        control, recorded only), read the guard's counters and log around the container sweep,
        then always remove the route and verify that it is gone."""
        if (record.get('provisioning') or {}).get('egress_falsification') is not True:
            return False, {'error': 'not available: the instance was not created with '
                                    'create --provision --egress-falsification'}
        detail = {'decision_rule': 'PASS: every container target refused with the guard\'s TCP '
                                   'reset or ICMP reject, the guard\'s IPv4 REJECT counters up by '
                                   'exactly the attempts, and the LOG lines show OUT= the guest '
                                   'uplink; FAIL: any timeout or ENETUNREACH from a container with '
                                   'the route present; STOP: any connection',
                  'targets': EGRESS_ROUTE_TARGETS, 'routes_before': ipv4_routes()}
        verdict = (False, [], [], {})
        requested = False
        serial = int(route_report(-1, ['present', 'removed', 'REMAINS', 'refused'], 0)
                     .get('serial') or 0)
        try:
            touched = ssh.run(['touch', EGRESS_ROUTE_REQUEST], timeout=60)
            requested = touched.returncode == 0
            present = route_report(serial, ['present', 'removed', 'REMAINS', 'refused'])
            detail['route_present_report'] = {k: present.get(k) for k in (
                'serial', 'state', 'uplink', 'before', 'present', 'error', 'wait')}
            detail['routes_with_route'] = ipv4_routes()
            uplink = present.get('uplink')
            want = f'default via {EGRESS_ROUTE_GATEWAY} dev {uplink}'
            if present.get('state') != 'present' or \
                    not any(line.startswith(want) for line in detail['routes_with_route']):
                detail['error'] = 'the route was not present'
            else:
                spec = {'targets': EGRESS_ROUTE_TARGETS, 'timeout': JOB_CONNECT_S}
                arg = base64.b64encode(json.dumps(spec).encode('utf-8')).decode('ascii')
                before, log_before = egress_counters(facts())
                results = []
                for cid in conversations:
                    data = _job_json(in_container(cid, container_python(JOB_EGRESS_SWEEP, arg), 120))
                    results += [dict(r, conversation=cid) for r in data.get('results') or []]
                after, log_after = egress_counters(facts())
                verdict = egress_route_verdict(results, before, after, log_after.get('tail'), uplink)
                stop_conditions.extend(verdict[2])
                detail['complete'] = len(results) == len(EGRESS_ROUTE_TARGETS) * len(conversations)
                if not verdict[2]:
                    control_spec = {'targets': EGRESS_ROUTE_CONTROL, 'timeout': JOB_CONNECT_S}
                    control = ssh.run(['python3', '-', base64.b64encode(json.dumps(
                        control_spec).encode('utf-8')).decode('ascii')],
                        input_text=JOB_EGRESS_SWEEP, timeout=120)
                    detail['guest_control'] = (_job_json(control.stdout).get('results')
                                               if control.returncode == 0 else
                                               {'rc': control.returncode})
                detail.update(results=verdict[1], counters=verdict[3],
                              guard_log={'count_before': log_before.get('count'),
                                         'count_after': log_after.get('count')})
        finally:
            # always: ask the root unit to remove the route, and verify that it is gone
            if requested:
                ssh.run(['touch', EGRESS_ROUTE_OFF], timeout=60)
                removed = route_report(serial, ['removed', 'REMAINS', 'refused'])
                detail['route_removed_report'] = {k: removed.get(k) for k in (
                    'serial', 'state', 'ended_by', 'after', 'error', 'wait')}
            detail['routes_after'] = ipv4_routes()
            detail['route_gone'] = not any(line.startswith('default')
                                           for line in detail['routes_after'])
            if not detail['route_gone']:
                stop_conditions.append({'condition': 'the temporary default route remains in the '
                                                     'guest; destroy it'})
        ok = verdict[0] and detail.get('complete') is True and detail['route_gone'] and \
            requested and (detail.get('route_removed_report') or {}).get('state') == 'removed'
        return ok, detail

    def keep_answer(label, result):
        """Take the whole answer out of a JOB_INFERENCE_TOKEN result (it is never recorded) and
        keep it in memory for the provider-key search."""
        encoded = result.pop('answer_b64', None)
        if encoded is not None:
            answers.append((label, base64.b64decode(encoded)))
        if result.get('answer_omitted') is not None:
            memo.setdefault('omitted', []).append(label)
        return result

    def inference_step():
        """Decision 0015 section 4.5, on an instance with the inference composition only: from
        inside each job the endpoint without a token, the allow's edges, the resolver and a
        name lookup, the container guard's IPv4 refusal counters read before and after; and
        once from the guest's own login (outside every container) the endpoint without a
        token, answered by the broker's token admission alone."""
        spec = inference_job_spec(profile)
        arg = base64.b64encode(json.dumps(spec).encode('utf-8')).decode('ascii')
        before = container_guard_rejects(facts())
        results = []
        for cid in conversations:
            data = _job_json(in_container(cid, container_python(JOB_INFERENCE_SWEEP, arg), 300))
            results += [dict(r, conversation=cid) for r in data.get('results') or []]
        after = container_guard_rejects(facts())
        login_spec = dict(inference_token_spec(profile, {'routes': [{'method': 'GET', 'path': '/'}],
                                                         'auth': {'header': 'authorization',
                                                                  'scheme': None}}, None, False),
                          body={})
        address, port = spec['endpoint']
        login = keep_answer('guest login, no token', _job_json(ssh.run(
            ['python3', '-', base64.b64encode(json.dumps(login_spec).encode('utf-8')).decode('ascii')],
            input_text=JOB_INFERENCE_TOKEN, timeout=120).stdout))
        results.append({'proto': 'tcp', 'host': address, 'port': port, 'what': INFERENCE_GUEST_WHAT,
                        'outcome': login.get('outcome'), 'status': login.get('status'),
                        'refusal': login.get('refusal'), 'conversation': 'guest login (agent)'})
        ok, rows, stop, counters = inference_job_verdict(results, before, after)
        stop_conditions.extend(stop)
        complete = len(results) == (len(spec['targets']) + 2) * len(conversations) + 1
        return ok and complete, {
            'decision_rule': 'PASS: the endpoint answers 401 without a token from every job and '
                             'from the guest login (TOKEN_MISSING: the token is the only admission '
                             'control there), every edge and resolver target is refused '
                             '(ECONNREFUSED) with the container guard\'s IPv4 REJECT counters up '
                             'by at least the refused attempts, and the name lookup returns no '
                             'address; STOP: an edge or resolver target connects or answers, a '
                             'name resolves, or the guest login is admitted without a token',
            'spec': spec, 'results': rows, 'counters': counters, 'complete': complete}

    def attempt_token_step():
        """Decision 0015 sections 3.3 and 4.4 from inside the token's own job, by the rule of
        inference_token_verdict; the forward session is stopped once and re-established."""
        status, grant = broker.call('status'), broker.call('grant', token_fp)
        family = next((f for f in status.get('families') or []
                       if isinstance(f, dict) and f.get('id') == grant.get('family')), None)
        detail = {'token_fingerprint': token_fp,
                  'grant': {k: grant.get(k) for k in ('state', 'family', 'models', 'conversation_id',
                                                      'attempt_id', 'budget', 'expires_at')},
                  'family': None if family is None else {k: family.get(k) for k in (
                      'id', 'status', 'routes', 'auth', 'ready', 'upstream')},
                  'decision_rule': 'PASS: with the token the upstream answers (2xx, no broker '
                                   'refusal); after revocation 401 TOKEN_REVOKED; with the forward '
                                   'stopped ECONNREFUSED; after it is re-established 401 '
                                   'TOKEN_REVOKED; the token never echoed. STOP: a revoked token '
                                   'forwarded, or an answer without the forward'}
        cid = grant.get('conversation_id')
        if grant.get('state') != 'live' or family is None or family.get('ready') is not True or \
                not grant.get('models') or cid not in state['created']:
            detail['error'] = ('the grant must be live, its family ready, and it must be bound to '
                               'one of the probe\'s conversations')
            return False, detail
        if not forward.status()['held']:
            detail['error'] = 'no forward session is held: run inference-forward --action start first'
            return False, detail

        def once(phase):
            spec = inference_token_spec(profile, family, grant['models'][0], True)
            arg = base64.b64encode(json.dumps(spec).encode('utf-8')).decode('ascii')
            return keep_answer(f'the job, {phase}', _job_json(in_container(cid, container_python_sealed(
                JOB_INFERENCE_TOKEN, arg, attempt_token), 120, secret=attempt_token)))
        phases = {'forwarded': once('forwarded')}
        counted = broker.call('grant', token_fp)
        phases['broker_counts'] = {k: counted.get(k) for k in ('requests', 'refused', 'usage')}
        revoked = broker.call('revoke', token_fp, 'attempt end', INFERENCE_REVOKER)
        memo['token_revoked'] = True
        phases['revocation'] = {'state': revoked.get('state'), 'revocation': revoked.get('revocation')}
        phases['after_revocation'] = once('after revocation')
        stopped = forward.stop()
        phases['forward_stop'] = {'result': stopped.get('result')}
        try:
            phases['without_forward'] = once('without the forward')
        finally:
            started = forward.start()
            phases['forward_restart'] = {'result': started.get('result'),
                                         'existing': started.get('existing')}
        phases['re_established'] = once('forward re-established')
        ok, checks, stop = inference_token_verdict(phases)
        stop_conditions.extend(stop)
        return ok and stopped.get('result') == 'stopped' and started.get('result') == 'held', \
            dict(detail, conversation=cid, phases=phases, checks=checks)

    def key_search_step():
        """S-03.2's proof as amended: the provider key itself, raw and encoded, in every answer the
        endpoint gave in the guest (what crossed the forward), searched on the host in memory."""
        omitted = memo.get('omitted', [])
        report = forward_answers_search(provider_key, answers)
        if report['verdict'] == 'found':
            stop_conditions.append({'condition': 'the provider key crossed the forward to the guest',
                                    'surfaces': [s['label'] for s in report['surfaces'] if s['found']]})
        detail = {'decision_rule': 'PASS: every answer kept whole and the search not-found with valid '
                                   'controls; STOP: the key found in an answer',
                  'answers': len(answers), 'omitted': omitted, 'search': report}
        return report['verdict'] == 'not-found' and bool(answers) and not omitted, detail

    def attempt_revoke_step():
        """The dispatcher revokes the token at attempt end (decision 0015 section 3.3) when the
        token step did not."""
        grant = broker.call('grant', token_fp)
        if grant.get('state') == 'live':
            grant = broker.call('revoke', token_fp, 'attempt end', INFERENCE_REVOKER)
        return grant.get('state') == 'revoked', {
            'token_fingerprint': token_fp, 'state': grant.get('state'),
            'revocation': grant.get('revocation'), 'by_token_step': bool(memo.get('token_revoked'))}

    def delete_step():
        out = {}
        for cid in list(state['created']):
            response, = call({'method': 'DELETE', 'path': f'/api/conversations/{cid}',
                              'timeout': 300})
            out[cid] = response.get('status')
            if _status_ok(response):
                state['created'].remove(cid)
        report = facts()
        view, ok = conversation_containers_view(profile, record, report)
        count, = call({'method': 'GET', 'path': '/api/conversations/count'})
        return not state['created'] and ok and view.get('count') == 0 and count.get('body') == 0, {
            'delete': out, 'containers_after': view.get('count'), 'count_after': count.get('body')}

    run('trusted side with the key (positive control)', trusted_step)
    run('create two disposable conversations (positive control)', create_step)
    run('job environment as inspected (docker inspect, root facts)', inspected_step)
    run('job environment from inside (identity, capabilities, variables, root)', env_step)
    run('engine sockets from inside each job', socket_step)
    run('engine API over TCP, guest and host aliases, from inside each job', tcp_step)
    run('privileged Agent Server routes from inside each job, every address', routes_step)
    run('credentials by name and fingerprint inside each job', token_step)
    run('hardening controls present (boot facts)', controls_step)
    run('route-present egress falsification from inside each job (S-01.4)', route_step)
    run('egress sweep from inside each job (S-01.4)', egress_step,
        always=not stop_conditions and 'route-present egress falsification from inside each job '
                                       '(S-01.4)' in failed)
    if inference_opted(record):
        run(INFERENCE_JOB_STEP, inference_step)
    if token_fp is not None:
        run(INFERENCE_TOKEN_STEP, attempt_token_step)
        if provider_key is not None:
            run(INFERENCE_KEY_SEARCH_STEP, key_search_step, always=True)
        run(INFERENCE_REVOKE_STEP, attempt_revoke_step, always=True)
    run('delete the conversations (positive control)', delete_step,
        always=bool(state['created']))
    out = {'schema': JOB_PROBE_SCHEMA, 'operation': 'job-access-probe',
           'labels': labels(profile), 'profile': profile['name'], 'instance': name,
           'conversations': conversations, 'started_at': started, 'ended_at': utc_now(),
           'seconds': round(time.time() - t0, 1),
           'ci': {'status': 'not applicable yet: no CI runner exists',
                  'constraints': (jobs.get('ci') or {}).get('constraints'),
                  'carried_to': (jobs.get('ci') or {}).get('carried_to')},
           'result': 'PASS' if not failed and not stop_conditions else 'FAIL',
           'failed_steps': failed, 'stop_conditions': stop_conditions, 'steps': steps}
    if token_fp is not None:
        out = redact_secret(out, attempt_token, f'<attempt token {token_fp} redacted>')
        out['attempt_token'] = {'fingerprint': token_fp,
                                'redacted_from_record': out.pop('redactions'),
                                'echoes_redacted_in_guest': memo.get('token_echoes', 0)}
    if provider_key is not None and \
            key_search().Search(provider_key).holds(json.dumps(out, sort_keys=True, default=str)):
        raise Refused('SECRET', 'the job-access-probe record would hold the provider key: not written')
    out['record'] = write_record(idir, 'job-access-probe', out)
    if out_file is not None:
        write_json_exclusive(out_file, json.loads(json.dumps(out, default=str)))
        out['out'] = str(out_file)
    return out


# ---------------------------------------------------------------- containment probes (S-02.1)

CONTAINMENT_SCHEMA = 'ai-engineering-harness/profiles/containment-probe-record/v1'
CONTAINMENT_CATALOGUE = ('security', 'containment-cases.json')
# The two disposable conversations of the containment probe's own cases (the fixture with
# these ids); admission-probe and job-access-probe create and delete their own.
CONTAINMENT_CONVERSATIONS = ('a0221b00-0000-4000-8000-000000000c01',
                             'a0221b00-0000-4000-8000-000000000c02')
CONTAINMENT_PLACEHOLDERS = ('own_hex', 'peer_hex', 'own_canary', 'peer_canary', 'uid')
CONTAINMENT_SECRET_NAMES = ('OH_SECRET_KEY', 'OH_SESSION_API_KEYS_0')
DISK_FSTYPES = frozenset({'ext2', 'ext3', 'ext4', 'xfs', 'btrfs', 'vfat', 'f2fs'})
SHARE_FSTYPE_SET = frozenset(SHARE_FSTYPES.split(','))
# Moby's per-container files bound from its data root
DOCKER_FILE_MOUNTS = ('/etc/resolv.conf', '/etc/hostname', '/etc/hosts')

# Run inside a conversation container as its default user (python3; spec as zlib-compressed
# base64 JSON {scratch, workspace, attempts: [{key, op, args}], cleanup, own_binds}; see
# container_python_z). Each operation is one of the
# catalogue's closed, non-destructive set (tools/check_containment_cases.py OPS); writes go
# only to the probe's own scratch directories, which cleanup removes. Outcomes are errno
# names or a class; no file content and no secret value is printed.
CONTAINMENT_PROBE = r'''import base64, ctypes, errno, hashlib, json, os, platform, secrets, shutil, socket, stat, subprocess, sys, time, zlib
spec = json.loads(zlib.decompress(base64.b64decode(sys.argv[1])).decode('utf-8'))
SCR, WS = spec['scratch'], spec['workspace']
MARK = ('aieh' + '-' + 'canary').encode()
WS_MARK = 'aieh-ws-' + 'canary-'
libc = ctypes.CDLL(None, use_errno=True)
libc.syscall.restype = ctypes.c_long
os.makedirs(SCR, exist_ok=True)
FLAGS = {'user': 0x10000000, 'mount': 0x00020000, 'net': 0x40000000}
DEV_DEFAULT = {'console', 'core', 'fd', 'full', 'mqueue', 'null', 'ptmx', 'pts', 'random', 'shm',
               'stderr', 'stdin', 'stdout', 'tty', 'urandom', 'zero'}
def ename(exc):
    n = getattr(exc, 'errno', None)
    if isinstance(n, int) and n:
        return errno.errorcode.get(n, str(n))
    return type(exc).__name__
def cerr():
    n = ctypes.get_errno()
    return errno.errorcode.get(n, str(n))
def scratch(name):
    os.makedirs(SCR, exist_ok=True)
    return os.path.join(SCR, name)
def op_read(a):
    try:
        fd = os.open(a['path'], os.O_RDONLY | os.O_NONBLOCK | os.O_NOCTTY)
    except OSError as exc:
        return {'outcome': ename(exc)}
    try:
        st = os.fstat(fd)
        n = len(os.read(fd, 4096)) if stat.S_ISREG(st.st_mode) else None
        return {'outcome': 'ok', 'bytes_read': n, 'type': stat.S_IFMT(st.st_mode)}
    except OSError as exc:
        return {'outcome': 'ok', 'read_error': ename(exc)}
    finally:
        os.close(fd)
def op_list(a):
    try:
        return {'outcome': 'ok', 'entries': len(os.listdir(a['path']))}
    except OSError as exc:
        return {'outcome': ename(exc)}
def op_stat(a):
    try:
        st = os.lstat(a['path'])
        return {'outcome': 'ok', 'type': stat.S_IFMT(st.st_mode)}
    except OSError as exc:
        return {'outcome': ename(exc)}
def op_access_write(a):
    r = libc.access(a['path'].encode(), 2)
    return {'outcome': 'ok' if r == 0 else cerr()}
def op_own_workspace(a):
    os.makedirs(WS, exist_ok=True)
    name = 'ws-canary-' + secrets.token_hex(8) + '.txt'
    data = (WS_MARK + secrets.token_hex(16) + '\n').encode()
    path = os.path.join(WS, name)
    with open(path, 'xb') as fh:
        fh.write(data)
    with open(path, 'rb') as fh:
        back = fh.read()
    listed = name in os.listdir(WS)
    good = back == data and listed
    return {'outcome': 'ok' if good else 'mismatch', 'name': name,
            'sha256': hashlib.sha256(data).hexdigest(), 'listed': listed}
def op_proc_root_search(a):
    rel = WS.lstrip('/') + '/' + a['name']
    pids = ['self'] if a.get('self_only') else sorted(d for d in os.listdir('/proc') if d.isdigit())
    found, errs = [], {}
    for pid in pids:
        try:
            os.lstat('/proc/%s/root/%s' % (pid, rel))
            found.append(pid)
        except OSError as exc:
            errs[ename(exc)] = errs.get(ename(exc), 0) + 1
    return {'outcome': 'found' if found else 'not-found', 'pids': len(pids), 'found_in': found,
            'errors': errs}
def mounts():
    out = []
    for line in open('/proc/self/mountinfo').read().splitlines():
        left, _, right = line.partition(' - ')
        f, r = left.split(), right.split()
        if len(f) < 6 or len(r) < 2:
            continue
        out.append({'dev': f[2], 'root': f[3], 'target': f[4], 'options': f[5],
                    'optional': f[6:], 'fstype': r[0], 'source': r[1]})
    return out
def op_mountinfo(a):
    return {'outcome': 'collected', 'mounts': mounts()}
def op_writable_scan(a):
    ms = mounts()
    own = spec['own_binds']
    if a.get('own_binds'):
        res = {d: libc.access(d.encode(), 2) == 0 for d in own}
        conv = [d for d in own if d.startswith('/var/openhands/conversations/')]
        listing = {}
        for d in conv:
            try:
                listing[d] = sorted([n, libc.access(os.path.join(d, n).encode(), 2) == 0]
                                    for n in os.listdir(d))[:40]
            except OSError as exc:
                listing[d] = ename(exc)
        return {'outcome': 'ok' if len(res) == 3 and all(res.values()) else 'not-writable',
                'binds': res, 'own_conversation_store': listing}
    uid = os.getuid()
    writable, scanned, roots = [], 0, []
    for m in ms:
        if m['fstype'] not in spec['disk_fstypes'] or m['target'] in own:
            continue
        roots.append(m['target'])
        todo = [m['target']]
        while todo and scanned < 20000:
            p = todo.pop()
            scanned += 1
            try:
                st = os.lstat(p)
            except OSError:
                continue
            if libc.access(p.encode(), 2) == 0 and not stat.S_ISLNK(st.st_mode):
                writable.append([p, st.st_uid, st.st_uid == uid])
            if stat.S_ISDIR(st.st_mode):
                try:
                    todo.extend(os.path.join(p, n) for n in os.listdir(p))
                except OSError:
                    pass
    return {'outcome': 'writable-found' if writable else 'none', 'mount_points': roots,
            'scanned': scanned, 'writable': writable[:40]}
def op_canary_scan(a):
    os.makedirs(WS, exist_ok=True)
    control = os.path.join(WS, 'canary-control-' + secrets.token_hex(8))
    with open(control, 'xb') as fh:
        fh.write(MARK + b'-control-' + secrets.token_hex(16).encode() + b'\n')
    hits, control_found = [], False
    stats = {'files': 0, 'unreadable': 0, 'over_bound': 0, 'process_files': 0}
    t0 = time.monotonic()
    for root, dirs, files in os.walk('/', onerror=lambda e: None):
        if root in ('/proc', '/sys', '/dev'):
            dirs[:] = []
            continue
        for n in files:
            p = os.path.join(root, n)
            try:
                st = os.lstat(p)
                if not stat.S_ISREG(st.st_mode):
                    continue
                if st.st_size > spec['max_bytes']:
                    stats['over_bound'] += 1
                    continue
                with open(p, 'rb') as fh:
                    data = fh.read()
            except OSError:
                stats['unreadable'] += 1
                continue
            stats['files'] += 1
            if MARK in data:
                if p == control:
                    control_found = True
                    if not a.get('include_control'):
                        continue
                hits.append(p)
    for d in sorted(os.listdir('/proc')):
        if d.isdigit():
            for part in ('environ', 'cmdline'):
                try:
                    data = open('/proc/%s/%s' % (d, part), 'rb').read()
                except OSError:
                    stats['unreadable'] += 1
                    continue
                stats['process_files'] += 1
                if MARK in data:
                    hits.append('/proc/%s/%s' % (d, part))
    return dict(stats, outcome='found' if hits else 'not-found', hits=hits[:40],
                control_outcome='found' if control_found else 'not-found',
                seconds=round(time.monotonic() - t0, 1))
def op_unix_control(a):
    path = scratch('ctl.sock')
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    cli = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        srv.bind(path)
        srv.listen(1)
        cli.settimeout(4)
        cli.connect(path)
        return {'outcome': 'connected'}
    except OSError as exc:
        return {'outcome': ename(exc)}
    finally:
        cli.close()
        srv.close()
        if os.path.lexists(path):
            os.unlink(path)
def op_connect_tcp(a):
    if a['host'] != '127.0.0.1':
        return {'outcome': 'refused-by-probe'}
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(4)
    try:
        s.connect((a['host'], int(a['port'])))
        return {'outcome': 'connected'}
    except socket.timeout:
        return {'outcome': 'timeout'}
    except OSError as exc:
        return {'outcome': ename(exc)}
    finally:
        s.close()
def op_socket(a):
    kind = socket.SOCK_RAW if a['type'] == 'raw-icmp' else socket.SOCK_DGRAM
    try:
        s = socket.socket(socket.AF_INET, kind, socket.IPPROTO_ICMP)
    except OSError as exc:
        return {'outcome': ename(exc)}
    s.close()
    return {'outcome': 'ok'}
def op_unshare(a):
    mask = 0
    for f in a['flags']:
        mask |= FLAGS[f]
    pid = os.fork()
    if pid == 0:
        r = libc.unshare(ctypes.c_int(mask))
        os._exit(0 if r == 0 else (ctypes.get_errno() or 255) & 0xff)
    _, status = os.waitpid(pid, 0)
    code = os.waitstatus_to_exitcode(status)
    return {'outcome': 'ok' if code == 0 else errno.errorcode.get(code, 'exit %d' % code)}
def op_fork_control(a):
    pid = os.fork()
    if pid == 0:
        os._exit(0)
    _, status = os.waitpid(pid, 0)
    code = os.waitstatus_to_exitcode(status)
    return {'outcome': 'ok' if code == 0 else errno.errorcode.get(code, 'exit %d' % code)}
def op_mknod(a):
    if a['kind'] == 'char':
        path, mode, dev = scratch('aieh-null'), stat.S_IFCHR | 0o600, os.makedev(1, 3)
    else:
        path, mode, dev = scratch('aieh-fifo'), stat.S_IFIFO | 0o600, 0
    try:
        os.mknod(path, mode, dev)
        return {'outcome': 'ok'}
    except OSError as exc:
        return {'outcome': ename(exc)}
def op_init_module(a):
    if platform.machine() != 'x86_64':
        return {'outcome': 'unsupported-arch'}
    if a['variant'] == 'control':
        r = libc.syscall(ctypes.c_long(39))
        return {'outcome': 'ok' if r == os.getpid() else 'unexpected'}
    r = libc.syscall(ctypes.c_long(175), ctypes.c_char_p(b''), ctypes.c_ulong(0), ctypes.c_char_p(b''))
    return {'outcome': 'ok' if r == 0 else cerr()}
def op_ptrace_read(a):
    child = subprocess.Popen(['sleep', '1'], stdin=subprocess.DEVNULL)
    try:
        fd = os.open('/proc/%d/mem' % child.pid, os.O_RDONLY)
        os.close(fd)
        return {'outcome': 'ok'}
    except OSError as exc:
        return {'outcome': ename(exc)}
    finally:
        child.wait()
def op_proc_census(a):
    me, foreign, seen = os.getuid(), [], 0
    for d in sorted(x for x in os.listdir('/proc') if x.isdigit()):
        try:
            lines = open('/proc/%s/status' % d).read().splitlines()
        except OSError:
            continue
        seen += 1
        info = {k: v.split() for k, _, v in (l.partition(':') for l in lines) if k in ('Uid', 'Name')}
        uid = int((info.get('Uid') or ['-1'])[0])
        if uid != me:
            try:
                fd = os.open('/proc/%s/mem' % d, os.O_RDONLY)
                os.close(fd)
                mem = 'ok'
            except OSError as exc:
                mem = ename(exc)
            foreign.append([d, ' '.join(info.get('Name') or []), uid, mem])
    if not foreign:
        outcome = 'none-visible'
    elif any(f[3] == 'ok' for f in foreign):
        outcome = 'foreign-mem-readable'
    else:
        outcome = 'foreign-visible-denied'
    return {'outcome': outcome, 'processes': seen, 'foreign': foreign[:20]}
def op_dev_list(a):
    names = sorted(os.listdir('/dev'))
    extra = sorted(set(names) - DEV_DEFAULT)
    return {'outcome': 'extra-devices' if extra else 'default-set', 'names': names, 'extra': extra}
def op_exec(a):
    try:
        r = subprocess.run(a['argv'], capture_output=True, text=True, timeout=30,
                           stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        return {'outcome': 'absent'}
    except subprocess.TimeoutExpired:
        return {'outcome': 'timeout'}
    out = ' '.join((r.stdout + r.stderr).split())[:240]
    return {'outcome': 'ok' if r.returncode == 0 else 'refused', 'rc': r.returncode, 'out': out}
def op_net_ifaces(a):
    names = sorted(os.listdir('/sys/class/net'))
    outcome = 'bridge' if names == ['eth0', 'lo'] else ('none' if names == ['lo'] else 'other')
    return {'outcome': outcome, 'interfaces': names}
OPS = {'read': op_read, 'list': op_list, 'stat': op_stat, 'access-write': op_access_write,
       'own-workspace': op_own_workspace, 'proc-root-search': op_proc_root_search,
       'mountinfo': op_mountinfo, 'writable-scan': op_writable_scan, 'canary-scan': op_canary_scan,
       'unix-control': op_unix_control, 'connect-tcp': op_connect_tcp, 'socket': op_socket,
       'unshare': op_unshare, 'fork-control': op_fork_control, 'mknod': op_mknod, 'init-module': op_init_module,
       'ptrace-read': op_ptrace_read, 'proc-census': op_proc_census, 'dev-list': op_dev_list,
       'exec': op_exec, 'net-ifaces': op_net_ifaces}
results = {}
for item in spec['attempts']:
    t0 = time.monotonic()
    try:
        res = OPS[item['op']](item.get('args') or {})
    except Exception as exc:
        res = {'outcome': 'probe-error', 'error': (type(exc).__name__ + ': ' + str(exc))[:200]}
    res['seconds'] = round(time.monotonic() - t0, 2)
    results[item['key']] = res
out = {'uid': os.getuid(), 'gid': os.getgid(), 'groups': os.getgroups(), 'results': results}
if spec.get('cleanup'):
    for d in (SCR, WS):
        shutil.rmtree(d, ignore_errors=True)
    out['cleanup'] = {d: os.path.lexists(d) for d in (SCR, WS)}
print('AIEH-JOB-JSON ' + json.dumps(out, sort_keys=True))
'''


_CONTAINMENT_CHECKER = []


def container_python_z(script, spec):
    """container_python with the script and its JSON spec zlib-compressed: the operator API
    carries each request as one SSH argument, and Windows caps a command line at 32 KiB."""
    s = base64.b64encode(zlib.compress(script.encode('utf-8'), 9)).decode('ascii')
    a = base64.b64encode(zlib.compress(json.dumps(spec).encode('utf-8'), 9)).decode('ascii')
    return (f"echo {s} | base64 -d | python3 -c 'import sys, zlib; sys.stdout.buffer.write("
            f"zlib.decompress(sys.stdin.buffer.read()))' > /tmp/aieh-job.py && "
            f"python3 /tmp/aieh-job.py {a}; rc=$?; rm -f /tmp/aieh-job.py; exit $rc")


def load_containment_checker():
    """tools/check_containment_cases.py (loaded once): the catalogue's rules and its closed
    vocabularies (operations, extractors, success outcomes) that this runner implements."""
    if not _CONTAINMENT_CHECKER:
        spec = importlib.util.spec_from_file_location(
            'check_containment_cases', REPO / 'tools' / 'check_containment_cases.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _CONTAINMENT_CHECKER.append(module)
    return _CONTAINMENT_CHECKER[0]


def load_containment_catalogue(ctx):
    """(catalogue, sha256, checker module): the committed catalogue, refused unless the
    checker passes it (a catalogue that fails its own rules never runs)."""
    checker = load_containment_checker()
    path = ctx.repo.joinpath(*CONTAINMENT_CATALOGUE)
    data = path.read_bytes()
    catalogue = json.loads(data.decode('utf-8'))
    inventory = json.loads(ctx.repo.joinpath(catalogue.get('inventory', '')).read_text(encoding='utf-8'))
    problems = checker.check(catalogue, inventory, ctx.repo)
    if problems:
        raise Refused('REFUSED', f'{"/".join(CONTAINMENT_CATALOGUE)} fails its checker '
                      f'({len(problems)} problem(s)); run tools/check_containment_cases.py',
                      [str(p) for p in problems[:20]])
    return catalogue, hashlib.sha256(data).hexdigest(), checker


def _step_of(record, name):
    """The step entry of a primitive's record, or None (skipped or absent)."""
    for s in (record or {}).get('steps') or []:
        if isinstance(s, dict) and s.get('step') == name and 'skipped' not in s:
            return s
    return None


def _obs(where, outcome, **detail):
    return dict({'where': where, 'outcome': str(outcome)}, **detail)


def _job_step(record, name):
    return _step_of(record, name) or {}


JOB_STEPS = {
    'trusted': 'trusted side with the key (positive control)',
    'inspected': 'job environment as inspected (docker inspect, root facts)',
    'env': 'job environment from inside (identity, capabilities, variables, root)',
    'socket': 'engine sockets from inside each job',
    'tcp': 'engine API over TCP, guest and host aliases, from inside each job',
    'routes': 'privileged Agent Server routes from inside each job, every address',
    'tokens': 'credentials by name and fingerprint inside each job',
    'controls': 'hardening controls present (boot facts)',
    'egress-route': 'route-present egress falsification from inside each job (S-01.4)',
    'egress': 'egress sweep from inside each job (S-01.4)',
    'inference': INFERENCE_JOB_STEP,
}
ADMISSION_STEPS = {
    'sweep': 'unauthenticated and wrong-key requests to every route',
    'trusted': 'trusted side with the key (positive control)',
    'network': 'agent network: listener, guest services, published ports, peer',
    'custody': 'agent network: session keys and start_child_conversation',
    'keycheck': 'key check fails closed',
    'logged': 'refusals logged',
}


def _norm_net(outcome):
    out = str(outcome)
    return 'answered' if out.startswith('answered') else out


def extract_job(record, extract, args, context):
    """Observations of one job-access-probe case from its record."""
    def detail_of(key):
        step = _step_of(record, JOB_STEPS[key])
        return (step or {}).get('detail') if step else None
    out = []
    if extract == 'socket':
        d = detail_of('socket')
        pattern = re.compile('^' + re.escape(args['path']).replace(re.escape('{uid}'), r'\d+') + '$')
        for cid, per in (d or {}).items():
            for who, entry in (per or {}).items():
                for row in (entry or {}).get('attempts') or []:
                    if pattern.match(str(row.get('path', ''))):
                        out.append(_obs(f'{cid} {who}', row.get('observed'), path=row.get('path')))
    elif extract == 'sockets-found':
        d = detail_of('socket')
        for cid, per in (d or {}).items():
            for who, entry in (per or {}).items():
                rows = [r for r in (entry or {}).get('attempts') or [] if r.get('declared') is False]
                if not rows:
                    out.append(_obs(f'{cid} {who}', 'none'))
                for row in rows:
                    got = row.get('observed')
                    out.append(_obs(f'{cid} {who}', 'refused' if got in ('ENOENT', 'ECONNREFUSED',
                                                                         'EACCES') else got,
                                    path=row.get('path')))
    elif extract == 'inference':
        d = detail_of('inference')
        for row in (d or {}).get('results') or []:
            if row.get('what') != args['what']:
                continue
            got = row.get('outcome')
            if row.get('what') == INFERENCE_ENDPOINT_WHAT and got == 'answered':
                got = 'answered' if row.get('status') == 401 else f"answered-{row.get('status')}"
            elif row.get('what') == INFERENCE_GUEST_WHAT and got == 'answered':
                got = 'token-refused' if row.get('status') == 401 and \
                    row.get('refusal') == 'TOKEN_MISSING' else f"answered-{row.get('status')}"
            out.append(_obs(row.get('conversation'), got,
                            target=f"{row.get('proto')} {row.get('host')}:{row.get('port')}"))
    elif extract == 'tcp':
        d = detail_of('tcp')
        for cid, c in ((d or {}).get('containers') or {}).items():
            for row in c.get('targets') or []:
                if row.get('what') == args['what']:
                    got = row.get('observed')
                    if args['what'].endswith('(control)') and got == 'connected' and not row.get('ok'):
                        got = 'connected-without-200'
                    out.append(_obs(cid, got, target=row.get('target'), answer=row.get('answer')))
    elif extract == 'routes':
        d = detail_of('routes')
        for cid, c in ((d or {}).get('containers') or {}).items():
            for host, h in (c.get('hosts') or {}).items():
                outcomes = set((h.get('outcomes') or {}))
                if h.get('answered'):
                    got = 'answered'
                elif outcomes == {'refused'} and h.get('attempts') == 2 * (d.get('routes') or -1):
                    got = 'refused'
                else:
                    got = 'other: ' + ','.join(sorted(outcomes))
                out.append(_obs(f'{cid} {host}', got, attempts=h.get('attempts')))
    elif extract in ('tokens', 'credential-files', 'token-control'):
        d = detail_of('tokens')
        searched = (d or {}).get('searched') or {}
        label = args.get('label', '')
        for cid, c in ((d or {}).get('containers') or {}).items():
            if extract == 'credential-files':
                out.append(_obs(cid, 'found' if c.get('credential_files') else 'none',
                                files=c.get('credential_files')))
                continue
            if extract == 'token-control':
                out.append(_obs(cid, 'found' if c.get('control_found') else 'not-found'))
                continue
            hits = [h[1] for h in c.get('hits') or [] if isinstance(h, list) and len(h) == 2]
            if label == 'gitea:*':
                want = sorted(context.get('gitea_labels') or [])
                have = set(searched.get('gitea (sha256 prefix)') or [])
                missing = [w for w in want if w not in have]
                if not want or missing:
                    got = 'not-searched'
                else:
                    got = 'found' if any(str(h).startswith('gitea:') for h in hits) else 'absent'
                out.append(_obs(cid, got, searched=sorted(have), missing=missing))
            else:
                family, _, name_ = label.partition(':')
                have = set(searched.get('outer (aieh v1)') or []) if family == 'aieh' else set()
                if name_ not in have:
                    out.append(_obs(cid, 'not-searched'))
                else:
                    out.append(_obs(cid, 'found' if label in hits else 'absent'))
    elif extract == 'env':
        d = detail_of('env')
        field = args['field']
        for cid, c in (d or {}).items():
            st, p1 = c.get('status') or {}, c.get('pid1_status') or {}
            if field in ('sudo', 'su'):
                r = c.get(field)
                got = 'absent' if r is None else ('root-obtained' if r.get('rc') == 0 else 'refused')
                out.append(_obs(cid, got, rc=(r or {}).get('rc'), out=(r or {}).get('out')))
            elif field in ('no_new_privs', 'seccomp'):
                key = {'no_new_privs': 'NoNewPrivs', 'seccomp': 'Seccomp'}[field]
                got = st.get(key) if st.get(key) == p1.get(key) else f'mixed {st.get(key)}/{p1.get(key)}'
                out.append(_obs(cid, got))
            elif field == 'capabilities':
                caps = [s.get(k) for s in (st, p1) for k in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd',
                                                             'CapAmb')]
                got = 'empty' if caps and all(v == '0' * 16 for v in caps) else 'present'
                out.append(_obs(cid, got, CapEff=st.get('CapEff'), CapBnd=st.get('CapBnd')))
            elif field == 'apparmor':
                out.append(_obs(cid, c.get('apparmor')))
            elif field == 'variable-names':
                allowed = set(context.get('secret_names') or CONTAINMENT_SECRET_NAMES)
                extra = sorted({n for e in (c.get('process_environments') or {}).values()
                                for n in (e.get('names') or []) if n not in allowed})
                got = 'extra' if extra or c.get('terminal_names') else 'only-own-keys'
                out.append(_obs(cid, got, extra=extra, terminal=c.get('terminal_names')))
    elif extract == 'inspected':
        step = _step_of(record, JOB_STEPS['inspected'])
        d = (step or {}).get('detail') or {}
        if args['field'] == 'declared':
            if step:
                out.append(_obs('guest', 'as-declared' if step.get('ok') else 'loosened',
                                containers=len(d.get('effective') or [])))
        else:
            for c in d.get('effective') or []:
                value = (c.get('HostConfig') or {}).get(args['field'])
                got = ','.join(str(v) for v in value) if isinstance(value, list) else str(value)
                out.append(_obs(c.get('conversation') or c.get('id'), got))
    elif extract == 'controls':
        step = _step_of(record, JOB_STEPS['controls'])
        observed = ((step or {}).get('detail') or {}).get('observed')
        if isinstance(observed, dict):
            key = args['key']
            if key == 'observed':
                out.append(_obs('guest', 'ok' if all(k in observed for k in (
                    'daemon.json icc', 'SecurityOptions', 'guard unit', 'key check ExecStartPre'))
                    else 'incomplete'))
            elif key == 'SecurityOptions':
                have = observed.get(key) if isinstance(observed.get(key), list) else []
                missing = [o for o in context.get('required_security_options') or [] if o not in have]
                out.append(_obs('guest', 'missing' if missing or not have else 'includes-required',
                                missing=missing))
            elif key in observed:
                out.append(_obs('guest', observed.get(key)))
    elif extract == 'egress':
        d = detail_of('egress')
        for r in (d or {}).get('results') or []:
            what = str(r.get('what', ''))
            if what == args['what'] or (args['what'] == 'public literal' and
                                         what.startswith('public literal')):
                out.append(_obs(f"{r.get('conversation')} {r.get('proto')}:{r.get('host')}:{r.get('port')}",
                                _norm_net(r.get('outcome')), verdict=r.get('verdict')))
    elif extract == 'egress-route':
        step = _step_of(record, JOB_STEPS['egress-route'])
        d = (step or {}).get('detail') or {}
        if step and str(d.get('error', '')).startswith('not available'):
            out.append(_obs('guest', 'not-available', error=d.get('error')))
        elif step:
            rows = d.get('results') or []
            counters = d.get('counters') or {}
            for r in rows:
                got = _norm_net(r.get('outcome'))
                if got not in ('connected', 'answered'):
                    got = 'refused-by-guard' if step.get('ok') and got == EGRESS_REFUSED else \
                        f'guard-not-proved ({got})'
                out.append(_obs(f"{r.get('conversation')} {r.get('proto')}:{r.get('host')}:{r.get('port')}",
                                got))
            if not rows:
                out.append(_obs('guest', 'guard-not-proved (no attempt)', error=d.get('error')))
            for o in out:
                o.update(counters_exact=counters.get('exact'),
                         log_out_uplink=counters.get('log_out_uplink'), route_gone=d.get('route_gone'))
    elif extract == 'trusted':
        step = _step_of(record, JOB_STEPS['trusted'])
        if step:
            out.append(_obs('guest', 'ok' if step.get('ok') else 'failed'))
    return out


def extract_admission(record, extract, args, context):
    """Observations of one admission-probe case from its record."""
    step = _step_of(record, ADMISSION_STEPS[extract])
    if not step:
        return []
    d = step.get('detail') or {}
    if extract == 'sweep':
        answered = [s for s in (record or {}).get('stop_conditions') or []
                    if 'without the key' in str(s.get('condition'))]
        got = 'answered-2xx' if answered else ('refused-as-inventoried' if step.get('ok') else 'mismatch')
        return [_obs('guest', got, routes=d.get('routes'), outcomes=d.get('outcomes'),
                     mismatches=len(d.get('mismatches') or []))]
    if extract == 'network':
        out = []
        for cid, c in (d.get('containers') or {}).items():
            for row in c.get('targets') or []:
                if row.get('what') == args['what']:
                    out.append(_obs(cid, row.get('observed'), target=row.get('target')))
        return out
    if extract == 'custody':
        out = []
        for cid, c in (d.get('containers') or {}).items():
            got = 'found' if c.get('outer_fingerprint_found') else \
                ('inner-only' if c.get('ok') else 'mismatch')
            out.append(_obs(cid, got, target=c.get('internal_server_url'),
                            child=c.get('start_child_conversation_target')))
        return out
    if extract == 'keycheck':
        return [_obs('guest', 'fails-closed' if step.get('ok') else 'keycheck-open')]
    if extract == 'logged':
        return [_obs('guest', 'logged' if step.get('ok') else 'not-logged')]
    if extract == 'trusted':
        return [_obs('guest', 'ok' if step.get('ok') else 'failed')]
    return []


CONTAINMENT_EXTRACTORS = {'job-access-probe': extract_job, 'admission-probe': extract_admission}
CONTAINMENT_EXTRACT_NAMES = {
    'job-access-probe': ('socket', 'sockets-found', 'tcp', 'routes', 'tokens', 'credential-files',
                         'token-control', 'env', 'inspected', 'controls', 'egress', 'egress-route',
                         'trusted', 'inference'),
    'admission-probe': tuple(ADMISSION_STEPS)}
CONTAINMENT_OP_NAMES = ('read', 'list', 'stat', 'access-write', 'own-workspace', 'proc-root-search',
                        'mountinfo', 'writable-scan', 'canary-scan', 'unix-control', 'connect-tcp',
                        'socket', 'unshare', 'fork-control', 'mknod', 'init-module', 'ptrace-read', 'proc-census',
                        'dev-list', 'exec', 'net-ifaces')


def own_bind_destinations(profile, hex_id):
    return [m['destination'].replace('{conversation_hex}', hex_id)
            for m in conversations_config(provisioning_config(profile)).get('mounts') or []]


def mountinfo_outcome(check, mounts, own_dests, peer_mounts=None):
    """The outcome of a mountinfo case from the parsed /proc/self/mountinfo of the job (and,
    for shared-with-peer, of its peer)."""
    disk = [m for m in mounts or [] if m.get('fstype') in DISK_FSTYPES]
    if check == 'own-binds':
        targets = {m.get('target') for m in disk}
        return ('found' if own_dests and all(d in targets for d in own_dests) else 'missing',
                {'own_binds': own_dests})
    if check == 'share':
        shares = [m for m in mounts or [] if m.get('fstype') in SHARE_FSTYPE_SET or
                  str(m.get('fstype', '')).startswith('fuse')]
        undeclared = [m for m in disk if m.get('target') not in own_dests and
                      m.get('target') not in DOCKER_FILE_MOUNTS]
        if shares:
            return 'share-found', {'shares': shares}
        if undeclared:
            return 'undeclared-mount', {'undeclared': undeclared}
        return 'no-share', {'disk_mounts': [m.get('target') for m in disk]}
    if check == 'shared-with-peer':
        if peer_mounts is None:
            return 'peer-not-observed', {}
        mine = {(m.get('dev'), m.get('root')) for m in disk}
        theirs = {(m.get('dev'), m.get('root')) for m in peer_mounts if m.get('fstype') in DISK_FSTYPES}
        shared = sorted([list(x) for x in mine & theirs])
        nested = sorted([[a[0], a[1], b[1]] for a in mine for b in theirs if a[0] == b[0] and a != b and
                         (b[1].startswith(a[1].rstrip('/') + '/') or a[1].startswith(b[1].rstrip('/') + '/'))])
        if shared or nested:
            return 'shared-with-peer', {'shared': shared, 'nested': nested}
        return 'none-shared', {'compared': [len(mine), len(theirs)]}
    return 'unknown-check', {}


def containment_verdict(case, observations, control_verdict, compensating=None):
    """(verdict, reason, stop) of one case under the catalogue's rule for its kind. A success
    outcome of a denial is a FAIL and a stop condition; a denial whose positive control did
    not pass is UNKNOWN, never PASS; a missing observation is a FAIL, never skipped."""
    checker = load_containment_checker()
    success_set = checker.SUCCESS_OUTCOMES
    kind = case.get('kind')
    expected = set((case.get('expected') or {}).get('outcomes') or [])
    outcomes = [str(o.get('outcome')) for o in observations]
    if kind == 'permitted':
        if not outcomes:
            return 'FAIL', 'not observed', False
        bad = sorted({o for o in outcomes if o not in expected})
        return ('FAIL', f'unexpected {bad}', False) if bad else ('PASS', 'succeeded', False)
    success = sorted({o for o in outcomes if o in success_set})
    if success:
        return 'FAIL', f'the attempt succeeded: {success}', kind == 'denial'
    if control_verdict != 'PASS':
        return 'UNKNOWN', f"positive control {case.get('positive_control')} is {control_verdict}", False
    if not outcomes:
        return 'FAIL', 'not observed (a case is never skipped)', False
    bad = sorted({o for o in outcomes if o not in expected})
    if bad:
        return 'FAIL', f'outside the expected outcomes: {bad}', False
    if kind == 'deviation':
        failing = sorted(cid for cid, v in (compensating or {}).items() if v != 'PASS')
        if failing or not compensating:
            return 'FAIL', f'compensating cases not PASS: {failing}', False
    return 'PASS', 'as expected', False


def container_inspect_digest(container, hex_id, keys):
    """sha256 of one container's normalized docker inspect: what the job environment
    depends on, with the conversation id and the ephemeral host port replaced."""
    host = container.get('HostConfig') or {}
    config = container.get('Config') or {}
    norm = {'Image': container.get('Image'), 'Config.Image': config.get('Image'),
            'Config.User': config.get('User'), 'AppArmorProfile': container.get('AppArmorProfile'),
            'HostConfig': {k: host.get(k) for k in sorted(keys)}}
    norm['HostConfig']['Binds'] = sorted(str(b).replace(hex_id, '{conversation_hex}')
                                         for b in host.get('Binds') or [])
    ports = host.get('PortBindings') or {}
    norm['HostConfig']['PortBindings'] = {p: [{'HostIp': (b or {}).get('HostIp')} for b in v or []]
                                          for p, v in sorted(ports.items())}
    return hashlib.sha256(json.dumps(norm, sort_keys=True, default=str).encode('utf-8')).hexdigest()


def guard_counters(report):
    adm = report.get('admission') if isinstance(report.get('admission'), dict) else {}
    container = {fam: [r.get('packets') for r in adm.get(fam) or [] if isinstance(r, dict)]
                 for fam in ('iptables', 'ip6tables')}
    egress, log_ = egress_counters(report)
    return ({'counters': container, 'log_count': (adm.get('log') or {}).get('count')},
            {'iptables': egress, 'log_count': log_.get('count')})


def profile_block_digests(profile):
    return {k: hashlib.sha256(json.dumps(profile.get(k), sort_keys=True).encode('utf-8')).hexdigest()
            for k in ('launch', 'network', 'host_shares')}


def containment_probe(ctx, name, out_path=None, token_fingerprints=None, sensitivity=False,
                      channels=None, ssh_fn=None, admission_fn=None, job_fn=None,
                      defective_controls=()):
    """containment-probe (S-02.1) on a running provisioned instance: the versioned catalogue
    (security/containment-cases.json, refused unless its checker passes) run in one pass.
    admission-probe and job-access-probe run unchanged for the cases they cover; the rest
    run inside two further disposable conversation containers as the job's default user,
    with generated canary workspaces. Every case gets its attempt, principal, observations,
    classification, control result and verdict (PASS, FAIL or UNKNOWN), and the run a
    runtime-configuration snapshot before and after. ``sensitivity`` also runs the
    catalogue's mutations, each of which must be classified a success (FAIL). A denial that
    succeeds is a stop condition: later primitives are not started. One machine verdict:
    PASS only when every case passed. ``channels``, ``ssh_fn``, ``admission_fn`` and
    ``job_fn`` stand in for the guest in tests. ``defective_controls`` (E-01.2.2 slice (b),
    TEST ONLY, drill instances only) replaces the named positive controls with an attempt that
    cannot succeed: their cases must become UNKNOWN and the run must not PASS."""
    idir = ctx.instance_dir(name)
    _, record = running_instance(ctx, name)
    if defective_controls and (record.get('validation') or {}).get('mode') != 'drill':
        raise Refused('REFUSED', '--drill-defective-control runs on a drill instance only '
                      '(create --provision --drill); an acceptance run never takes it')
    if not record.get('provisioning'):
        raise Refused('REFUSED', f'{name} was not created with --provision; it runs no Agent Server')
    if not jobs_config(ctx.profile) or not admission_config(ctx.profile):
        raise Refused('REFUSED', 'the profile declares no provisioning.agent_server.jobs and admission')
    out_file = None
    if out_path:
        out_file = Path(out_path).resolve()
        if os.path.lexists(out_file) or not out_file.parent.is_dir() or \
                inside(out_file, ctx.repo) or inside(out_file, idir):
            raise Refused('REFUSED', f'--out {out_path}: must be a new file in an existing '
                          'directory, outside the checkout and the instance directory')
    catalogue, catalogue_sha, checker = load_containment_catalogue(ctx)
    catalogue, injected = defective_catalogue(catalogue, defective_controls) \
        if defective_controls else (catalogue, [])
    gitea = dict((catalogue.get('fingerprints') or {}).get('gitea') or {})
    extra = parse_token_fingerprints(token_fingerprints)
    for label, fp in extra.items():
        gitea.setdefault(label, fp)
    fingerprint_args = [f'{k}={v}' for k, v in sorted(gitea.items())]
    profile = ctx.profile
    jobs = jobs_config(profile)
    server = provisioning_config(profile)['agent_server']
    scratch = catalogue['scratch']
    cases = [c for c in catalogue['cases'] if c.get('status') == 'executable']
    by_id = {c['id']: c for c in cases}
    body_a, fixture_problems, _ = _fixture(ctx)
    bodies = [dict(body_a, conversation_id=cid, tags={'aieh': 's-02.1-containment'})
              for cid in CONTAINMENT_CONVERSATIONS]
    conversations = list(CONTAINMENT_CONVERSATIONS)

    def default_channels(rec):
        ssh = Ssh(profile, idir, rec['ports']['ssh'])
        return GuestApi(ssh, profile), GuestFacts(ssh, profile)
    channels = channels or default_channels
    ssh = (ssh_fn or (lambda rec: Ssh(profile, idir, rec['ports']['ssh'])))(record)
    api, facts = channels(record)
    admission_fn = admission_fn or (lambda: admission_probe(ctx, name, channels=channels,
                                                            ssh_fn=ssh_fn))
    job_fn = job_fn or (lambda: job_access_probe(ctx, name, token_fingerprints=fingerprint_args,
                                                 channels=channels, ssh_fn=ssh_fn))
    t0, started = time.time(), utc_now()
    steps, failed, stop_conditions = [], [], []
    state = {'created': []}
    memo = {'primitives': {}, 'own': {}, 'mutations': {}}
    caught = (Refused, OSError, ValueError, KeyError, TypeError, IndexError,
              subprocess.SubprocessError)

    def run(step, func, always=False):
        if stop_conditions and not always:
            steps.append({'step': step, 'skipped': 'a stop condition was reached'})
            return None
        s = time.time()
        entry = {'step': step, 'started_at': utc_now()}
        try:
            ok, detail = func()
        except caught as exc:
            ok, detail = False, {'error': getattr(exc, 'code', type(exc).__name__),
                                 'message': str(exc), 'detail': getattr(exc, 'detail', None)}
        entry.update(seconds=round(time.time() - s, 1), ok=bool(ok), detail=detail)
        steps.append(entry)
        log(f'containment-probe: {step}: {"ok" if ok else "FAILED"} ({entry["seconds"]} s)')
        if not ok:
            failed.append(step)
        return detail

    def call(*requests):
        data = api(list(requests))
        if data.get('session_key_occurrences'):
            raise Refused('SECRET', 'a response carried the session key '
                          f'({data["session_key_occurrences"]} occurrence(s), redacted)')
        return data['responses']

    def in_container(conversation, command, timeout=600):
        response, = call({'method': 'POST',
                          'path': f'/api/conversations/{conversation}/bash/execute_bash_command',
                          'json': {'command': command, 'cwd': '/workspace', 'timeout': timeout},
                          'timeout': timeout + 60})
        body = response.get('body') if isinstance(response.get('body'), dict) else {}
        if not _status_ok(response) or body.get('exit_code') is None:
            raise Refused('CONTAINER', f'the command did not run in {conversation}: '
                          f'{json.dumps(response)[:400]}')
        return body.get('stdout') or ''

    def boot_facts():
        result = ssh.run(['python3', '-', provisioning_config(profile)['facts']['path']],
                         input_text='import json,sys\nprint(json.dumps(json.load(open(sys.argv[1]))))\n',
                         timeout=120)
        try:
            return json.loads(result.stdout.strip().splitlines()[-1])
        except (IndexError, ValueError):
            raise Refused('PROBE', f'no boot facts (rc {result.returncode})')

    def snapshot(phase):
        report = facts()
        boot = boot_facts()
        container_guard, egress_guard = guard_counters(report)
        daemon = boot.get('daemon_json') if isinstance(boot.get('daemon_json'), dict) else {}
        info = boot.get('info') if isinstance(boot.get('info'), dict) else {}
        adm = boot.get('admission') if isinstance(boot.get('admission'), dict) else {}
        prov = record.get('provisioning') or {}
        snap = {
            'phase': phase, 'collected_at': utc_now(),
            'container_guard': container_guard, 'egress_guard': egress_guard,
            'daemon': {'daemon_json_sha256': hashlib.sha256(json.dumps(
                daemon, sort_keys=True).encode('utf-8')).hexdigest(),
                'no-new-privileges': daemon.get('no-new-privileges'), 'icc': daemon.get('icc'),
                'hosts': daemon.get('hosts'), 'SecurityOptions': info.get('SecurityOptions'),
                'guard_unit': (adm.get('guard_unit') or {}).get('ActiveState')
                if isinstance(adm.get('guard_unit'), dict) else None,
                'key_check_exec_start_pre': (adm.get('keycheck') or {}).get('exec_start_pre')
                if isinstance(adm.get('keycheck'), dict) else None},
            'pins': {'profile_revision': record.get('profile_revision'),
                     'profile_sha256_launch': (record.get('profile') or {}).get('sha256'),
                     'profile_sha256_now': sha256_file(ctx.profile_path),
                     'profile_blocks': profile_block_digests(profile),
                     'inputs': {k: (v or {}).get('sha256') for k, v in
                                sorted((record.get('inputs') or {}).items())},
                     'provision_manifest_sha256': prov.get('manifest_sha256'),
                     'provision_lock_sha256': prov.get('lock_sha256'),
                     'image_id': prov.get('image_id'),
                     'agent_server_binary_sha256': (prov.get('agent_server') or {}).get('binary_sha256'),
                     'egress_falsification': prov.get('egress_falsification') is True,
                     'routes_sha256': admission_config(profile)['routes'].get('sha256'),
                     'fixture_sha256': server['fixture'].get('sha256'),
                     'catalogue_sha256': catalogue_sha,
                     'catalogue_version': catalogue.get('version')}}
        memo.setdefault('snapshots', {})[phase] = snap
        return True, snap

    def primitive(key, fn):
        def step():
            rec = fn()
            memo['primitives'][key] = rec
            stop_conditions.extend(dict(s, primitive=key) for s in rec.get('stop_conditions') or [])
            # the primitive's own verdict is evidence, not this step's: its cases are judged
            # one by one below
            return True, {'result': rec.get('result'), 'failed_steps': rec.get('failed_steps'),
                          'stop_conditions': rec.get('stop_conditions'),
                          'seconds': rec.get('seconds'), 'record': rec.get('record')}
        return step

    def create_step():
        out = {}
        for body in bodies:
            response, = call({'method': 'POST', 'path': '/api/conversations', 'json': body,
                              'timeout': 600})
            out[body['conversation_id']] = {'status': response.get('status'),
                                            'seconds': response.get('seconds')}
            if not _status_ok(response):
                return False, out
            state['created'].append(body['conversation_id'])
        report = facts()
        view, ok = conversation_containers_view(profile, record, report)
        keys = [k for k in (jobs.get('host_config') or {}) if k not in ('rule', 'AppArmorProfile')] + [
            'ExtraHosts', 'NetworkMode', 'ReadonlyRootfs', 'Ulimits', 'Runtime', 'Memory',
            'NanoCpus', 'PidsLimit', 'AutoRemove']
        digests = {}
        for c in report.get('containers') or []:
            hex_id = conversation_hex(c)
            digests[hex_id] = container_inspect_digest(c, hex_id, keys)
        memo['docker_inspect'] = {'fields': sorted(set(keys) | {'Image', 'Config.Image', 'Config.User',
                                                                 'AppArmorProfile', 'Binds',
                                                                 'PortBindings'}),
                                  'digests': digests, 'distinct': len(set(digests.values()))}
        memo['server_user'] = report.get('server_user') or {}
        return ok and view.get('count') == 2 and not fixture_problems and \
            len(set(digests.values())) == 1, {'create': out, 'containers': view,
                                              'docker_inspect': memo['docker_inspect'],
                                              'fixture_problems': fixture_problems}

    def container_run(cid, attempts, cleanup=False, timeout=900):
        own = [d for d in own_bind_destinations(profile, cid.replace('-', ''))]
        spec = {'scratch': scratch['container'], 'workspace': scratch['workspace'],
                'attempts': attempts, 'cleanup': cleanup, 'own_binds': own,
                'disk_fstypes': sorted(DISK_FSTYPES), 'max_bytes': JOB_SCAN_MAX_BYTES}
        return _job_json(in_container(cid, container_python_z(CONTAINMENT_PROBE, spec), timeout))

    def plant_step():
        out, ok_all = {}, True
        for cid in conversations:
            data = container_run(cid, [{'key': 'plant', 'op': 'own-workspace', 'args': {}},
                                       {'key': 'mountinfo', 'op': 'mountinfo',
                                        'args': {'check': 'collect'}}])
            res = data.get('results') or {}
            memo['own'][cid] = {'plant': res.get('plant') or {}, 'mountinfo': res.get('mountinfo') or {},
                                'uid': data.get('uid'), 'gid': data.get('gid'),
                                'groups': data.get('groups')}
            ok = (res.get('plant') or {}).get('outcome') == 'ok'
            ok_all = ok_all and ok
            out[cid] = {'identity': f"{data.get('uid')}:{data.get('gid')}",
                        'canary': {k: (res.get('plant') or {}).get(k) for k in ('name', 'sha256',
                                                                                 'listed', 'outcome')},
                        'mounts': len((res.get('mountinfo') or {}).get('mounts') or [])}
        return ok_all, out

    def substitute(value, cid):
        peer = conversations[1 - conversations.index(cid)]
        values = {'own_hex': cid.replace('-', ''), 'peer_hex': peer.replace('-', ''),
                  'own_canary': ((memo['own'].get(cid) or {}).get('plant') or {}).get('name'),
                  'peer_canary': ((memo['own'].get(peer) or {}).get('plant') or {}).get('name'),
                  'uid': (memo['own'].get(cid) or {}).get('uid')}
        if isinstance(value, str):
            for key in CONTAINMENT_PLACEHOLDERS:
                token = '{' + key + '}'
                if token in value:
                    if values.get(key) in (None, ''):
                        raise Refused('PROBE', f'placeholder {token} has no value for {cid}')
                    value = value.replace(token, str(values[key]))
            return value
        if isinstance(value, list):
            return [substitute(v, cid) for v in value]
        if isinstance(value, dict):
            return {k: substitute(v, cid) for k, v in value.items()}
        return value

    def exec_key(op, args):
        args = {k: v for k, v in (args or {}).items() if k not in ('report', 'profile_value')}
        if op == 'mountinfo':
            args = {}
        return op + ' ' + json.dumps(args, sort_keys=True)

    def attempts_step():
        out, ok_all = {}, True
        for cid in conversations:
            attempts, seen = [], set()
            for case in cases:
                probe = case['probe']
                if probe.get('source') != 'containment-probe' or probe['op'] in ('own-workspace',
                                                                                  'mountinfo'):
                    continue
                args = substitute(probe.get('args') or {}, cid)
                key = exec_key(probe['op'], args)
                if key not in seen:
                    seen.add(key)
                    attempts.append({'key': key, 'op': probe['op'],
                                     'args': {k: v for k, v in args.items()
                                              if k not in ('report', 'profile_value')}})
            data = container_run(cid, attempts)
            memo['own'][cid]['results'] = data.get('results') or {}
            memo['own'][cid]['attempts'] = attempts
            missing = [a['key'] for a in attempts if a['key'] not in (data.get('results') or {})]
            ok_all = ok_all and not missing
            out[cid] = {'attempts': len(attempts), 'missing': missing,
                        'outcomes': {k: v.get('outcome') for k, v in (data.get('results') or {}).items()}}
        return ok_all, out

    def mutation_step():
        out, ok_all = {}, True
        mutations = catalogue.get('mutations') or []
        cid = conversations[0]
        attempts = [{'key': m['id'], 'op': m['op'], 'args': substitute(m.get('args') or {}, cid)}
                    for m in mutations]
        data = container_run(cid, attempts)
        for m in mutations:
            res = (data.get('results') or {}).get(m['id']) or {}
            memo['mutations'][m['id']] = {'conversation': cid, 'attempt': attempts[mutations.index(m)],
                                          'result': res}
            out[m['id']] = res.get('outcome')
        return ok_all, out

    def cleanup_and_delete_step():
        out = {'cleanup': {}, 'delete': {}}
        for cid in list(state['created']):
            try:
                out['cleanup'][cid] = container_run(cid, [], cleanup=True, timeout=120).get('cleanup')
            except caught as exc:
                out['cleanup'][cid] = {'error': str(exc)[:200]}
        for cid in list(state['created']):
            response, = call({'method': 'DELETE', 'path': f'/api/conversations/{cid}',
                              'timeout': 300})
            out['delete'][cid] = response.get('status')
            if _status_ok(response):
                state['created'].remove(cid)
        report = facts()
        view, ok = conversation_containers_view(profile, record, report)
        count, = call({'method': 'GET', 'path': '/api/conversations/count'})
        cleaned = all(isinstance(v, dict) and not any(v.values()) for v in out['cleanup'].values())
        out.update(containers_after=view.get('count'), count_after=count.get('body'))
        return not state['created'] and ok and view.get('count') == 0 and count.get('body') == 0 \
            and cleaned, out

    run('catalogue checked (tools/check_containment_cases.py)', lambda: (True, {
        'path': '/'.join(CONTAINMENT_CATALOGUE), 'sha256': catalogue_sha,
        'version': catalogue.get('version'), 'cases': len(cases),
        'gitea_fingerprint_labels': sorted(gitea)}))
    run('runtime snapshot (before)', lambda: snapshot('before'))
    run('admission-probe (S-01.3.1 primitive, unchanged)', primitive('admission-probe', admission_fn))
    run('job-access-probe (S-01.3.2 and S-01.4 primitive, unchanged)',
        primitive('job-access-probe', job_fn))
    run('create two disposable containment conversations', create_step)
    if state['created']:
        run('plant generated canary workspaces (positive control)', plant_step)
        run('containment attempts from inside each job', attempts_step)
        if sensitivity:
            run('live sensitivity mutations', mutation_step)
    run('remove the probe scratch and delete the conversations', cleanup_and_delete_step,
        always=bool(state['created']))
    run('runtime snapshot (after)', lambda: snapshot('after'), always=True)

    # ---- classify every case
    context = {'gitea_labels': sorted(gitea),
               'secret_names': (jobs.get('environment') or {}).get('secret_names'),
               'required_security_options': (provisioning_config(profile).get('moby') or {})
               .get('required_security_options')}

    def own_observations(case, override=None):
        probe = override or case['probe']
        obs = []
        for cid in conversations:
            own = memo['own'].get(cid) or {}
            op_ = probe['op']
            if op_ == 'own-workspace':
                res = own.get('plant')
                if res:
                    obs.append(_obs(cid, res.get('outcome'), name=res.get('name')))
                continue
            if op_ == 'mountinfo':
                mounts = (own.get('mountinfo') or {}).get('mounts')
                if mounts is None:
                    continue
                peer = conversations[1 - conversations.index(cid)]
                peer_mounts = ((memo['own'].get(peer) or {}).get('mountinfo') or {}).get('mounts')
                got, detail = mountinfo_outcome(probe['args'].get('check'), mounts,
                                                own_bind_destinations(profile, cid.replace('-', '')),
                                                peer_mounts)
                obs.append(_obs(cid, got, **detail))
                continue
            if override is not None:
                res = (memo['mutations'].get(override['id']) or {}).get('result')
                if res and cid == memo['mutations'][override['id']]['conversation']:
                    obs.append(_obs(cid, res.get('outcome'), **{k: v for k, v in res.items()
                                                                 if k != 'outcome'}))
                continue
            results = own.get('results')
            if results is None:
                continue
            try:
                key = exec_key(op_, substitute(probe.get('args') or {}, cid))
            except Refused:
                continue
            res = results.get(key)
            if res is None:
                continue
            outcome = res.get('outcome')
            if op_ == 'canary-scan' and (probe.get('args') or {}).get('report') == 'control':
                outcome = res.get('control_outcome')
            obs.append(_obs(cid, outcome, **{k: v for k, v in res.items()
                                             if k not in ('outcome', 'control_outcome')}))
        return obs

    observations = {}
    for case in cases:
        probe = case['probe']
        source = probe.get('source')
        if source == 'containment-probe':
            observations[case['id']] = own_observations(case)
        else:
            rec = memo['primitives'].get(source)
            observations[case['id']] = CONTAINMENT_EXTRACTORS[source](
                rec, probe.get('extract'), probe.get('args') or {}, context) if rec else []
    verdicts, reasons = {}, {}
    order = [c for c in cases if c['kind'] == 'permitted'] + \
        [c for c in cases if c['kind'] in ('denial', 'hardening')] + \
        [c for c in cases if c['kind'] == 'deviation']
    for case in order:
        control = verdicts.get(case.get('positive_control')) if case.get('positive_control') else None
        comp = {cid: verdicts.get(cid) for cid in case.get('compensated_by') or []}
        verdict, reason, stop = containment_verdict(case, observations[case['id']], control, comp)
        verdicts[case['id']], reasons[case['id']] = verdict, reason
        if stop:
            stop_conditions.append({'condition': 'a denial probe succeeded', 'case': case['id'],
                                    'observations': observations[case['id']]})
    snapshots = memo.get('snapshots') or {}
    case_records = []
    for case in cases:
        snap = {}
        for key in case.get('depends_on') or []:
            if key == 'docker_inspect':
                snap[key] = memo.get('docker_inspect')
            else:
                snap[key] = {phase: (s or {}).get(key) for phase, s in snapshots.items()}
        case_records.append({
            'id': case['id'], 'category': case['category'], 'kind': case['kind'],
            'principal': case['principal'], 'attempt': case['attempt'], 'probe': case['probe'],
            'expected': case['expected']['outcomes'], 'enforcement': case['enforcement'],
            'observations': observations[case['id']],
            'classification': sorted({o['outcome'] for o in observations[case['id']]}),
            'positive_control': case.get('positive_control'),
            'control_verdict': verdicts.get(case.get('positive_control')),
            'compensated_by': {c: verdicts.get(c) for c in case.get('compensated_by') or []} or None,
            'verdict': verdicts[case['id']], 'reason': reasons[case['id']],
            'carried': case.get('carried'), 'snapshot': snap})
    sensitivity_rows = []
    if sensitivity:
        for m in catalogue.get('mutations') or []:
            case = by_id.get(m['case'])
            if case is None:
                continue
            override = {'id': m['id'], 'op': m['op'], 'args': m.get('args') or {}}
            obs = own_observations(case, override)
            verdict, reason, _ = containment_verdict(case, obs, verdicts.get(case.get('positive_control')))
            sensitivity_rows.append({'mutation': m['id'], 'case': m['case'], 'category': case['category'],
                                     'attempt': {'op': m['op'], 'args': m.get('args')},
                                     'observations': obs, 'classified': verdict, 'reason': reason,
                                     'expected': 'FAIL',
                                     'ok': verdict == 'FAIL' and any(o['outcome'] in checker.SUCCESS_OUTCOMES
                                                                     for o in obs)})
    totals = {v: sum(1 for x in verdicts.values() if x == v) for v in ('PASS', 'FAIL', 'UNKNOWN')}
    by_category = {}
    for case in cases:
        row = by_category.setdefault(case['category'], {'PASS': 0, 'FAIL': 0, 'UNKNOWN': 0})
        row[verdicts[case['id']]] += 1
    sensitivity_ok = all(r['ok'] for r in sensitivity_rows) if sensitivity else None
    if stop_conditions or totals['FAIL'] or failed or (sensitivity and not sensitivity_ok):
        result = 'FAIL'
    elif totals['UNKNOWN']:
        result = 'UNKNOWN'
    else:
        result = 'PASS'
    principal = {'uid_gid': sorted({f"{(o or {}).get('uid')}:{(o or {}).get('gid')}"
                                    for o in memo['own'].values()}),
                 'groups': sorted({str((o or {}).get('groups')) for o in memo['own'].values()}),
                 'server_user': memo.get('server_user')}
    out = {'schema': CONTAINMENT_SCHEMA, 'operation': 'containment-probe',
           'labels': labels(profile), 'profile': profile['name'], 'instance': name,
           'catalogue': {'path': '/'.join(CONTAINMENT_CATALOGUE), 'sha256': catalogue_sha,
                         'version': catalogue.get('version')},
           'conversations': conversations, 'principal': principal,
           'started_at': started, 'ended_at': utc_now(), 'seconds': round(time.time() - t0, 1),
           'result': result, 'totals': totals, 'by_category': by_category,
           'failed_steps': failed, 'stop_conditions': stop_conditions,
           'snapshots': snapshots, 'docker_inspect': memo.get('docker_inspect'),
           'cases': case_records,
           'sensitivity': {'ran': bool(sensitivity), 'ok': sensitivity_ok, 'rows': sensitivity_rows},
           'steps': steps, 'primitives': memo['primitives']}
    if injected:
        out['drill'] = {'defective_controls': injected, 'test_only': True,
                        'dependent_verdicts': {c: verdicts.get(c) for i in injected
                                               for c in i['dependent_cases']},
                        'control_verdicts': {i['control']: verdicts.get(i['control'])
                                             for i in injected}}
    out['record'] = write_record(idir, 'containment-probe', out)
    if out_file is not None:
        write_json_exclusive(out_file, json.loads(json.dumps(out, default=str)))
        out['out'] = str(out_file)
    return out


# ---------------------------------------------------------------- drills (E-01.2.2 slice (b))

# TEST-ONLY drill guests (plan leaf E-01.2.2 slice (b), under the Owner's extended guest-run
# authorization of 2026-11-07, evidence/bootstrap-log.md). `create --provision --drill` seeds
# tools/guest_drill.py as a second user-data part (cloud-init runs it once, as root, at first
# boot); it installs a root helper that acts on requests agent writes into a root:agent 0730
# directory. The profile's templates, its launch.argv and every ordinary create are
# unchanged; an ordinary instance never has the helper, and `drill` and `containment-probe
# --drill-defective-control` refuse any instance whose launch record is not a drill record.
# A drill instance has no guestfwd, host share or new host port, and it may be stopped and
# started (the guard drill boots it with a failing guard).
DRILL_SCRIPT = ('tools', 'guest_drill.py')
DRILL_BOUNDARY = '==AIEH-DRILL-USER-DATA=='
DRILL_REQUEST_DIR = '/var/lib/aieh-drill/request'
DRILL_RESULTS = '/var/lib/aieh-drill/results'
DRILL_CEILING_S = 600            # bounds a hang of one root request (most take 1-30 s)
DRILL_SCAN_CEILING_S = 2400      # the guest-root P5 scan (every file, optionally raw devices)
DRILL_SETTLE_S = 300             # units settling after a boot or a restart (a ceiling)
DRILL_SCHEMA = 'ai-engineering-harness/profiles/drill-record/v1'
DRILL_KINDS = ('fail-closed', 'stored-state', 'root-scan', 'f2-closed', 'restart-series',
               'admitted-create')
# The plan leaf each drill kind belongs to. A drill guest's launch record names the leaf it
# was created for (create --drill --drill-leaf); a drill of another leaf's kind is refused
# on it, and each drill record names its kind's leaf. Launch records written before
# --drill-leaf say 'E-01.2.2 slice (b)': drill_record_leaf reads them as E-01.2.2.
DRILL_KIND_LEAVES = {'fail-closed': 'E-01.2.2', 'stored-state': 'E-01.2.2',
                     'root-scan': 'E-01.2.2', 'f2-closed': 'E-01.2.2',
                     'admitted-create': 'E-01.2.2', 'restart-series': 'E-01.4.3'}
DRILL_LEAVES = tuple(sorted(set(DRILL_KIND_LEAVES.values())))
DRILL_AUTHORITY = ("the Owner's extended guest-run authorization of 2026-11-07 "
                   '(evidence/bootstrap-log.md)')
DRILL_GUARD_VARIANTS = ('fail-pre', 'check-only')
DRILL_KEY_VARIANTS = ('missing-session-key', 'second-session-key')
DRILL_SERVER_UNIT = 'aieh-agent-server.service'
DRILL_GUARD_UNIT = 'aieh-container-guard.service'
DRILL_QUIESCE_UNIT = 'aieh-agent-server-quiesce.service'
DRILL_QUIESCE_VARIANTS = ('fail-pre',)
DRILL_LISTENER = '127.0.0.1:8000'
# the conversations the drills create (the pinned fixture with these ids; never the fixture's)
DRILL_IDS = {
    'key-missing-session-key': 'e0122b00-0000-4000-8000-00000000c001',
    'key-second-session-key': 'e0122b00-0000-4000-8000-00000000c002',
    'guard-fail-pre': 'e0122b00-0000-4000-8000-00000000c011',
    'guard-check-only': 'e0122b00-0000-4000-8000-00000000c012',
    'quiesce-fail-pre': 'e0122c00-0000-4000-8000-00000000c021',
    'control': 'e0122b00-0000-4000-8000-00000000c0ff',
    'state': 'e0122b00-0000-4000-8000-00000000d001',
    'state-sensitivity': 'e0122b00-0000-4000-8000-00000000d0ff',
    # slice (c): the F-2 closed drill (decision rule fixed before observation)
    'f2-a': 'e0122c00-0000-4000-8000-00000000f20a',
    'f2-b1': 'e0122c00-0000-4000-8000-00000000f2b1',
    'f2-b2': 'e0122c00-0000-4000-8000-00000000f2b2',
    'f2-c': 'e0122c00-0000-4000-8000-00000000f20c',
    'f2-d': 'e0122c00-0000-4000-8000-00000000f20d',
    'f2-f-real': 'e0122c00-0000-4000-8000-00000000f2f1',
    'f2-f-foreign': 'e0122c00-0000-4000-8000-00000000f2f2',
    'f2-g-symlink': 'e0122c00-0000-4000-8000-00000000f2a1',
    'f2-g-hardlink': 'e0122c00-0000-4000-8000-00000000f2a2',
}
# where a path-like stored field is pointed: a directory the outer server could create
# (its ReadWritePaths) but no container mount reaches; its appearance is steering
DRILL_MARKER_ROOT = '/srv/scratch/openhands/home/aieh-drill'
DRILL_FOREIGN_UUID = 'e0122b00-0000-4000-8000-0000000000ff'
DRILL_CONTAINER_OPTIONS = {'memory': '8g', 'cpus': 4.0}
# a stored-state alteration must leave these container facts unchanged (the leaf's proof:
# runtime, image, mounts, caps, working_dir, key handling)
DRILL_SHAPE_HOST = ('Binds', 'Mounts', 'NetworkMode', 'CapAdd', 'CapDrop', 'SecurityOpt',
                    'Privileged', 'ReadonlyRootfs', 'Memory', 'MemorySwap', 'NanoCpus',
                    'CpuShares', 'CpuQuota', 'PidsLimit', 'Ulimits', 'UsernsMode', 'PidMode',
                    'IpcMode', 'UTSMode', 'CgroupnsMode', 'Devices', 'DeviceCgroupRules',
                    'Runtime', 'Init', 'Sysctls', 'GroupAdd', 'VolumesFrom', 'Tmpfs',
                    'ShmSize', 'CgroupParent', 'ExtraHosts', 'PortBindings', 'PublishAllPorts')
DRILL_DEFECTIVE_PROBE = {'source': 'containment-probe', 'op': 'read',
                         'args': {'path': '/aieh-drill-defective-control/absent'}}
DRILL_SERVER_SECRETS = ('OH_SECRET_KEY', 'OH_SESSION_API_KEYS_0', 'session.key')

# Run as agent: write the request (a temporary name, then renamed, so the path unit sees a
# complete file), then wait on inotify in the results directory for the result named by the
# request id, under a ceiling. Prints the result, or an error object, as one JSON line.
DRILL_REQUEST_PROBE = r'''import base64, ctypes, json, os, select, sys, time
req_dir, results, spec, ceiling = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])
req = json.loads(base64.b64decode(spec).decode('utf-8'))
target = os.path.join(results, req['id'] + '.json')
libc = ctypes.CDLL(None, use_errno=True)
fd = libc.inotify_init1(os.O_CLOEXEC)
if fd < 0 or libc.inotify_add_watch(fd, results.encode(), 0x80 | 0x8) < 0:
    print(json.dumps({'error': 'inotify', 'errno': ctypes.get_errno()})); sys.exit(3)
tmp = os.path.join(req_dir, '.request-' + req['id'] + '.tmp')
try:
    handle = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    os.write(handle, json.dumps(req).encode('utf-8'))
    os.close(handle)
    os.rename(tmp, os.path.join(req_dir, 'request.json'))
except OSError as exc:
    print(json.dumps({'error': 'request', 'errno': exc.errno})); sys.exit(3)
deadline = time.monotonic() + ceiling
while True:
    try:
        with open(target, encoding='utf-8') as h:
            print(json.dumps(json.load(h), sort_keys=True)); sys.exit(0)
    except (FileNotFoundError, ValueError):
        pass
    left = deadline - time.monotonic()
    if left <= 0:
        print(json.dumps({'error': 'ceiling', 'id': req['id']})); sys.exit(5)
    ready, _, _ = select.select([fd], [], [], min(5.0, left))
    if ready:
        os.read(fd, 65536)
'''


def drill_script(repo=REPO):
    """The guest-side root helper (tools/guest_drill.py): ASCII, LF, a python3 shebang."""
    path = Path(repo).joinpath(*DRILL_SCRIPT)
    raw = path.read_bytes()
    if b'\r' in raw or not raw.startswith(b'#!/usr/bin/python3\n'):
        raise Refused('REFUSED', f'{path}: the drill helper must start with #!/usr/bin/python3 '
                      'and carry no CR')
    try:
        raw.decode('ascii')
    except UnicodeDecodeError as exc:
        raise Refused('REFUSED', f'{path}: the drill helper is not ASCII ({exc})') from exc
    return raw


def drill_validation(script, seed_validation, leaf, repo=REPO):
    """The launch record's validation block of a drill instance created for ``leaf``."""
    if leaf not in DRILL_LEAVES:
        raise Refused('REFUSED', f'drill plan leaf {leaf!r} is not one of {list(DRILL_LEAVES)}')
    return {'mode': 'drill', 'test_only': True, 'plan_leaf': leaf,
            'authority': DRILL_AUTHORITY, 'single_boot': False, 'argv_changes': [],
            'guestfwd': None,
            'script': {'path': '/'.join(DRILL_SCRIPT), 'sha256': hashlib.sha256(script).hexdigest()},
            'seed': seed_validation}


def drill_record_leaf(record):
    """The plan leaf a drill guest's launch record names, as a leaf id ('E-01.2.2 slice (b)'
    of the records written before --drill-leaf reads as 'E-01.2.2'); None without one."""
    text = str(((record or {}).get('validation') or {}).get('plan_leaf') or '').split()
    return text[0] if text else None


def drill_instance(ctx, name):
    """(instance dir, launch record) of a running drill instance; anything else is refused."""
    idir, record = running_instance(ctx, name)
    if (record.get('validation') or {}).get('mode') != 'drill':
        raise Refused('REFUSED', f'{name} is not a drill instance (create --provision --drill); '
                      'a drill never runs on an ordinary instance')
    if not record.get('provisioning'):
        raise Refused('REFUSED', f'{name} was not created with --provision')
    return idir, record


class DrillChannel:
    """One root request of the drill helper, as agent over SSH; returns its result."""

    def __init__(self, ssh):
        self.ssh = ssh

    def __call__(self, action, params=None, ceiling=DRILL_CEILING_S):
        req = {'id': f'{action}-{secrets.token_hex(6)}', 'action': action, 'params': params or {}}
        spec = base64.b64encode(json.dumps(req).encode('utf-8')).decode('ascii')
        result = self.ssh.run(['python3', '-', DRILL_REQUEST_DIR, DRILL_RESULTS, spec, str(ceiling)],
                              input_text=DRILL_REQUEST_PROBE, timeout=ceiling + 60)
        try:
            data = json.loads(result.stdout.strip().splitlines()[-1])
        except (IndexError, ValueError):
            data = None
        if not isinstance(data, dict) or data.get('id') != req['id'] or 'error' in data and \
                'action' not in data:
            raise Refused('DRILL', f'drill {action}: no result (rc {result.returncode}): '
                          f'{(result.stdout or "")[-300:]} {result.stderr.strip()[-300:]}')
        if data.get('secret_occurrences_redacted'):
            log(f'drill {action}: {data["secret_occurrences_redacted"]} secret occurrence(s) '
                'redacted by the helper')
        return data


def _detail(result):
    if not result.get('ok'):
        raise Refused('DRILL', f'drill {result.get("action")}: {result.get("error")}')
    return result.get('detail') or {}


def _unit(obs, unit):
    return ((obs or {}).get('units') or {}).get(unit) or {}


def _listening(obs, address=DRILL_LISTENER):
    return any(str(line).split()[0] == address for line in (obs or {}).get('listeners') or []
               if str(line).split())


def _server_processes(obs):
    return [p for p in ((obs or {}).get('agent_server') or {}).get('processes') or []
            if p.get('comm') == 'agent-server']


def _moby_running(obs):
    return sorted({p.get('comm') for p in (obs or {}).get('moby_processes') or []})


def _settled(obs):
    """No unit of the chain is still starting."""
    return all(_unit(obs, u).get('ActiveState') not in ('activating', 'deactivating', 'reloading')
               for u in (DRILL_GUARD_UNIT, 'docker.service', DRILL_SERVER_UNIT))


def wait_until(fetch, done, ceiling_s):
    """(last value, met) of a condition that exposes no completion signal: fetch, test,
    and fetch again after POLL_S, under the ceiling."""
    deadline = time.monotonic() + ceiling_s
    while True:
        value = fetch()
        if done(value):
            return value, True
        if time.monotonic() >= deadline:
            return value, False
        time.sleep(POLL_S)


def _call(api, *requests):
    data = api(list(requests))
    if data.get('session_key_occurrences'):
        raise Refused('SECRET', 'a response carried the session key '
                      f'({data["session_key_occurrences"]} occurrence(s), redacted)')
    return data['responses']


def _reached(response):
    """True when an HTTP status came back (the server answered at all)."""
    return isinstance((response or {}).get('status'), int)


def check_row(name, ok, observed):
    return {'check': name, 'ok': bool(ok), 'observed': observed}


def key_drill_checks(during, ready, create, settled):
    """The failing key check (proof item 1): the server never runs and nothing answers."""
    unit = _unit(during, DRILL_SERVER_UNIT)
    lines = (during.get('journal') or {}).get(DRILL_SERVER_UNIT) or []
    return [
        check_row('Agent Server unit not active', unit.get('ActiveState') != 'active',
                  {k: unit.get(k) for k in ('ActiveState', 'SubState', 'Result', 'NRestarts')}),
        check_row('every start refused again (restarts observed)', settled, unit.get('NRestarts')),
        check_row('no agent-server process in its unit', not _server_processes(during),
                  _server_processes(during)),
        check_row(f'no listener on {DRILL_LISTENER}', not _listening(during),
                  during.get('listeners')),
        check_row('the key check refused (journal)',
                  any('aieh-agent-server-keycheck: refused' in str(line) for line in lines),
                  [line for line in lines if 'keycheck' in str(line)][-3:]),
        check_row('GET /ready gets no HTTP answer', not _reached(ready),
                  {k: ready.get(k) for k in ('status', 'error')}),
        check_row('POST /api/conversations gets no HTTP answer (no conversation)',
                  not _reached(create), {k: create.get(k) for k in ('status', 'error')}),
    ]


def guard_drill_checks(boot, after, ready, create):
    """The failing guard (proof item 1): Moby and the Agent Server stopped, no conversation."""
    guard, docker = _unit(boot, DRILL_GUARD_UNIT), _unit(boot, 'docker.service')
    server = _unit(boot, DRILL_SERVER_UNIT)
    shims = [c for c in _moby_running(after) if c.startswith('containerd-shim')]
    return [
        check_row('guard unit failed', guard.get('ActiveState') == 'failed',
                  {k: guard.get(k) for k in ('ActiveState', 'SubState', 'Result')}),
        check_row('docker.service not active (after boot and after the create attempt)',
                  docker.get('ActiveState') != 'active' and
                  _unit(after, 'docker.service').get('ActiveState') != 'active',
                  [{k: _unit(o, 'docker.service').get(k) for k in ('ActiveState', 'Result')}
                   for o in (boot, after)]),
        check_row('no dockerd process', 'dockerd' not in _moby_running(boot) + _moby_running(after),
                  {'boot': _moby_running(boot), 'after': _moby_running(after)}),
        check_row('Agent Server stopped', server.get('ActiveState') != 'active' and
                  not _server_processes(boot) and not _listening(boot),
                  {'unit': {k: server.get(k) for k in ('ActiveState', 'SubState', 'Result')},
                   'processes': _server_processes(boot), 'listening': _listening(boot)}),
        dependency_row(boot),
        check_row('no conversation created (no 2xx, no container)',
                  not _status_ok(create) and not shims,
                  {'create': {k: create.get(k) for k in ('status', 'error', 'body')},
                   'container_shims': shims}),
        check_row('GET /ready', True, {k: ready.get(k) for k in ('status', 'error')}),
    ]


DEPENDENCY_MARKERS = ('Dependency failed for', "result 'dependency'")


def dependency_row(obs):
    """The server's start job failed because a unit it Requires failed (E-01.2.2 slice (c):
    systemd logs it under the server's unit; the unit's own Result stays that of its last run)."""
    lines = ((obs or {}).get('journal') or {}).get(DRILL_SERVER_UNIT) or []
    found = [line for line in lines if any(m in str(line) for m in DEPENDENCY_MARKERS)]
    return check_row('Agent Server start refused with result dependency (journal)', bool(found),
                     found[-2:])


def quiesce_drill_checks(obs, ready, create):
    """A failing quiesce step (E-01.2.2 variant E): the server does not start."""
    step = _unit(obs, DRILL_QUIESCE_UNIT)
    return [
        check_row('quiesce step failed', step.get('ActiveState') == 'failed' or
                  step.get('Result') not in (None, '', 'success'),
                  {k: step.get(k) for k in ('ActiveState', 'SubState', 'Result')}),
        check_row('Agent Server not running', _unit(obs, DRILL_SERVER_UNIT).get('ActiveState') != 'active',
                  {k: _unit(obs, DRILL_SERVER_UNIT).get(k) for k in ('ActiveState', 'SubState', 'Result')}),
        dependency_row(obs),
        check_row(f'no listener on {DRILL_LISTENER}', not _listening(obs), obs.get('listeners')),
        check_row('no agent-server process in its unit', not _server_processes(obs),
                  _server_processes(obs)),
        check_row('GET /ready gets no HTTP answer', not _reached(ready),
                  {k: ready.get(k) for k in ('status', 'error')}),
        check_row('POST /api/conversations gets no HTTP answer (no conversation)',
                  not _reached(create), {k: create.get(k) for k in ('status', 'error')}),
    ]


def restored_checks(obs, ready):
    return [check_row(f'{u} active', _unit(obs, u).get('ActiveState') == 'active',
                      _unit(obs, u).get('ActiveState'))
            for u in (DRILL_GUARD_UNIT, 'docker.service', DRILL_SERVER_UNIT)] + \
        [check_row('guard drop-in absent', obs.get('guard_dropin_sha256') is None,
                   obs.get('guard_dropin_sha256')),
         check_row('GET /ready 200', (ready or {}).get('status') == 200, (ready or {}).get('status'))]


def drill_body(ctx, conversation_id):
    body, problems, _ = _fixture(ctx)
    if problems:
        raise Refused('REFUSED', f'the pinned fixture has problems: {problems}')
    out = copy.deepcopy(body)
    out['conversation_id'] = conversation_id
    out['tags'] = {'aieh': 'e-01.2.2-drill'}
    return out


def drill_fail_closed(ctx, name, steps, chan, reboot):
    """Proof item 1, the key check and the guard. ``chan()`` gives (api, facts, req) for the
    current boot; ``reboot()`` stops and starts the guest and returns its two records."""
    ready_req = {'method': 'GET', 'path': '/ready', 'auth': False, 'timeout': 15}

    def observe(paths=()):
        return _detail(chan()[2]('observe', {'paths': list(paths)}))

    def create_req(key):
        return {'method': 'POST', 'path': '/api/conversations', 'json': drill_body(ctx, DRILL_IDS[key]),
                'timeout': 300}

    def key_drill(variant):
        api, _, req = chan()
        pre = observe()
        n0 = int(_unit(pre, DRILL_SERVER_UNIT).get('NRestarts') or 0)
        broken = _detail(req('key-break', {'variant': variant}))
        during, settled = wait_until(
            observe, lambda o: int(_unit(o, DRILL_SERVER_UNIT).get('NRestarts') or 0) >= n0 + 2,
            DRILL_SETTLE_S)
        ready, create = _call(api, ready_req, create_req(f'key-{variant}'))
        after = observe()
        checks = key_drill_checks(during, ready, create, settled)
        checks.append(check_row('still stopped after the create attempt',
                                not _listening(after) and not _server_processes(after),
                                _unit(after, DRILL_SERVER_UNIT).get('ActiveState')))
        restored = _detail(req('key-restore'))
        post = observe()
        ready2, search = _call(api, ready_req, {'method': 'GET', 'path': '/api/conversations/search?limit=5'})
        restore = restored_checks(post, ready2) + [
            check_row('authenticated search 200', search.get('status') == 200, search.get('status')),
            check_row('the kept copy removed', restored.get('copy_removed') is True,
                      restored.get('copy_removed'))]
        ok = all(c['ok'] for c in checks)
        return ok and all(c['ok'] for c in restore), {
            'variant': variant, 'verdict': 'PASS' if ok else 'FAIL', 'break': broken,
            'checks': checks, 'restore_checks': restore, 'restore': restored,
            'observed': {'before': pre, 'during': during, 'after': after, 'restored': post}}

    def guard_drill(variant):
        _, _, req = chan()
        broken = _detail(req('guard-break', {'variant': variant}))
        boots = reboot()
        boot, settled = wait_until(observe, _settled, DRILL_SETTLE_S)
        api, _, req = chan()
        ready, create = _call(api, ready_req, create_req(f'guard-{variant}'))
        after = observe([f'/srv/scratch/openhands/conversations/'
                         f'{DRILL_IDS["guard-" + variant].replace("-", "")}'])
        checks = guard_drill_checks(boot, after, ready, create)
        checks.append(check_row('units settled after boot', settled,
                                {u: _unit(boot, u).get('ActiveState') for u in
                                 (DRILL_GUARD_UNIT, 'docker.service', DRILL_SERVER_UNIT)}))
        restored = _detail(req('guard-restore'))
        boots2 = reboot()
        post, settled2 = wait_until(observe, lambda o: _settled(o) and
                                    _unit(o, DRILL_SERVER_UNIT).get('ActiveState') == 'active',
                                    DRILL_SETTLE_S)
        api, facts, _ = chan()
        ready2, = _call(api, ready_req)
        ok = all(c['ok'] for c in checks)
        return ok and all(c['ok'] for c in restored_checks(post, ready2)), {
            'variant': variant, 'verdict': 'PASS' if ok else 'FAIL', 'break': broken,
            'reboot': boots, 'checks': checks, 'restore': restored, 'reboot_after_restore': boots2,
            'restore_checks': restored_checks(post, ready2),
            'observed': {'boot': boot, 'after_create': after, 'restored': post}}

    def control_create():
        """Positive control: with every control in place, a conversation is created (a
        container), then deleted; the drills' refused ids are deleted where they exist."""
        api, facts, _ = chan()
        created, = _call(api, create_req('control'))
        report = facts()
        hexes = [conversation_hex(c) for c in report.get('containers') or []]
        cleanup = {}
        for key in ['control'] + [k for k in DRILL_IDS if k.startswith(('key-', 'guard-', 'quiesce-'))]:
            got, = _call(api, {'method': 'DELETE', 'path': f'/api/conversations/{DRILL_IDS[key]}',
                               'timeout': 300})
            cleanup[key] = got.get('status')
        ok = _status_ok(created) and DRILL_IDS['control'].replace('-', '') in hexes and \
            cleanup['control'] == 200
        return ok, {'create': {k: created.get(k) for k in ('status', 'seconds')},
                    'containers': hexes, 'delete_status': cleanup}

    for variant in DRILL_KEY_VARIANTS:
        steps.run(f'key check fails closed ({variant})', lambda v=variant: key_drill(v))
    def quiesce_drill(variant):
        """E-01.2.2 slice (c), variant E: a drop-in breaks the quiesce step; a server restart
        and then a guest boot must leave the server not started (result dependency, no
        listener, no process); after the restore it serves again."""
        api, _, req = chan()
        key = f'quiesce-{variant}'
        broken = _detail(req('quiesce-break', {'variant': variant}))
        restart = restart_summary(_detail(req('server-restart')))
        after_restart, settled = wait_until(observe, _settled, DRILL_SETTLE_S)
        ready, create = _call(api, ready_req, create_req(key))
        checks = [dict(r, check='after a server restart: ' + r['check'])
                  for r in quiesce_drill_checks(after_restart, ready, create)]
        checks.append(check_row('after a server restart: systemctl restart reported the failure',
                                restart.get('rc') != 0, {k: restart.get(k) for k in ('rc', 'stderr')}))
        boots = reboot()
        boot, settled2 = wait_until(observe, _settled, DRILL_SETTLE_S)
        api, _, req = chan()
        ready_b, create_b = _call(api, ready_req, create_req(key))
        checks += [dict(r, check='after a guest boot: ' + r['check'])
                   for r in quiesce_drill_checks(boot, ready_b, create_b)]
        checks.append(check_row('units settled', settled and settled2, None))
        restored = _detail(req('quiesce-restore'))
        # restored by a boot, as the guard is: the boot-time facts that inspect reads are then
        # those of a boot with the step in place (a server restart would leave the broken
        # boot's facts behind)
        again = reboot()
        post, _ = wait_until(observe, lambda o: _settled(o) and
                             _unit(o, DRILL_SERVER_UNIT).get('ActiveState') == 'active', DRILL_SETTLE_S)
        api, _, req = chan()
        ready2, = _call(api, ready_req)
        restore = restored_checks(post, ready2) + [
            check_row('quiesce drop-in absent', post.get('quiesce_dropin_sha256') is None,
                      post.get('quiesce_dropin_sha256')),
            check_row('quiesce step succeeded at the restart',
                      _unit(post, DRILL_QUIESCE_UNIT).get('Result') == 'success',
                      _unit(post, DRILL_QUIESCE_UNIT).get('Result'))]
        ok = all(c['ok'] for c in checks)
        return ok and all(c['ok'] for c in restore), {
            'variant': variant, 'verdict': 'PASS' if ok else 'FAIL', 'break': broken,
            'restart': restart, 'reboot': boots, 'checks': checks, 'restore': restored,
            'reboot_after_restore': again, 'restore_checks': restore,
            'observed': {'after_restart': after_restart, 'boot': boot, 'restored': post}}

    for variant in DRILL_GUARD_VARIANTS:
        steps.run(f'guard fails closed ({variant})', lambda v=variant: guard_drill(v))
    for variant in DRILL_QUIESCE_VARIANTS:
        steps.run(f'quiesce step fails closed ({variant})', lambda v=variant: quiesce_drill(v))
    steps.run('positive control: create with every control in place', control_create, always=True)


class DrillSteps:
    """Named steps with their outcome; a failed restore stops every later step."""
    CAUGHT = (Refused, OSError, ValueError, KeyError, TypeError, IndexError, QmpError,
              subprocess.SubprocessError)

    def __init__(self, label):
        self.label, self.steps, self.failed, self.broken = label, [], [], None

    def run(self, step, func, always=False):
        if self.broken and not always:
            self.steps.append({'step': step, 'skipped': f'the guest state is unknown ({self.broken})'})
            return None
        s = time.time()
        entry = {'step': step, 'started_at': utc_now()}
        try:
            ok, detail = func()
        except self.CAUGHT as exc:
            ok, detail = False, {'error': getattr(exc, 'code', type(exc).__name__),
                                 'message': str(exc), 'detail': getattr(exc, 'detail', None)}
            self.broken = self.broken or step
        entry.update(seconds=round(time.time() - s, 1), ok=bool(ok), detail=detail)
        self.steps.append(entry)
        log(f'{self.label}: {step}: {"ok" if ok else "FAILED"} ({entry["seconds"]} s)')
        if not ok:
            self.failed.append(step)
        return detail


# ---------------------------------------------------------------- stored state (proof item 2)

UUID_TEXT = re.compile(r'^[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}$')
ISO_TIME = re.compile(r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}')
STEERING_KEY = re.compile(r'(?i)(dir|path|workspace|cwd|home|root|mount|volume)')


def mutate_value(key, value, marker):
    """One altered value for a stored field: type-preserving where the type is known, and
    aimed at steering where the field's name suggests a path, a runtime or an image."""
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 7
    if isinstance(value, float):
        return value + 1000.0
    if value is None:
        if STEERING_KEY.search(key):
            return marker
        if key == 'container':
            return dict(DRILL_CONTAINER_OPTIONS)
        if 'runtime' in key:
            return 'local'
        if 'image' in key:
            return 'busybox:latest'
        return 'aieh-drill'
    if isinstance(value, str):
        if key == 'execution_status':
            return 'running' if value != 'running' else 'idle'
        if value.startswith('/') or (STEERING_KEY.search(key) and not UUID_TEXT.match(value)):
            return marker
        if UUID_TEXT.match(value):
            return DRILL_FOREIGN_UUID if '-' in value else DRILL_FOREIGN_UUID.replace('-', '')
        if ISO_TIME.match(value):
            return '2001' + value[4:]
        if 'runtime' in key:
            return 'local'
        if 'image' in key:
            return 'busybox:latest'
        return value + '-aieh-drill'
    if isinstance(value, dict):
        return {'aieh-drill': 'x'}
    if isinstance(value, list):
        return value + ['aieh-drill']
    return 'aieh-drill'


def state_alterations(content, marker_root=DRILL_MARKER_ROOT):
    """Every field of every stored file, one alteration each (a field is a scalar, an empty
    object, or a list without objects; objects and lists of objects are walked), then the
    targeted additions: container options and a runtime in meta.json, and the startup
    hydration pair (execution_status running with a writable working_dir) together."""
    alts = []

    def add(file, pointer, old, new, marker=None, op='set'):
        alts.append({'n': len(alts), 'file': file, 'op': op, 'pointer': pointer, 'old': old,
                     'value': new, 'marker': marker})

    def walk(file, node, pointer):
        if isinstance(node, dict) and node:
            for k in sorted(node):
                walk(file, node[k], pointer + [k])
        elif isinstance(node, list) and node and all(isinstance(x, (dict, list)) for x in node):
            for i, x in enumerate(node):
                walk(file, x, pointer + [i])
        elif pointer:
            key = next((p for p in reversed(pointer) if isinstance(p, str)), '')
            marker = f'{marker_root}-{len(alts):03d}'
            new = mutate_value(key, node, marker)
            add(file, pointer, node, new, marker if new == marker else None)

    for file in ('meta.json', 'base_state.json', 'owner_lease.json'):
        if isinstance(content.get(file), (dict, list)):
            walk(file, content[file], [])
    meta = content.get('meta.json') if isinstance(content.get('meta.json'), dict) else {}
    if 'container' not in meta:
        add('meta.json', ['container'], '<absent>', dict(DRILL_CONTAINER_OPTIONS))
    if 'conversation_runtime' not in meta:
        add('meta.json', ['conversation_runtime'], '<absent>', 'local')
    if 'owner_lease.json' not in content:
        add('owner_lease.json', [], '<absent>',
            {'owner_instance_id': 'aieh-drill-foreign-owner', 'generation': 99,
             'expires_at': 4102444800.0}, op='plant')
    marker = f'{marker_root}-{len(alts):03d}'
    combo = [{'file': 'base_state.json', 'op': 'set', 'pointer': ['execution_status'],
              'value': 'running'}]
    if isinstance(meta.get('workspace'), dict):
        combo.append({'file': 'meta.json', 'op': 'set', 'pointer': ['workspace', 'working_dir'],
                      'value': marker})
    alts.append({'n': len(alts), 'combination': combo, 'marker': marker,
                 'why': 'the startup path: a RUNNING record is hydrated at server start '
                        '(ConversationService.__aenter__), with the stored working_dir'})
    return alts


def container_shape(container):
    """The facts of one conversation container that no stored field may change, with the
    conversation id normalized."""
    config, host = container.get('Config') or {}, container.get('HostConfig') or {}
    hex_id = conversation_hex(container) or '?'

    def norm(value):
        return json.loads(json.dumps(value, sort_keys=True).replace(hex_id, '{hex}'))
    labels_ = config.get('Labels') or {}
    return norm({
        'image': container.get('Image'), 'config_image': config.get('Image'),
        'user': config.get('User'), 'working_dir': config.get('WorkingDir'),
        'entrypoint': config.get('Entrypoint'), 'cmd': config.get('Cmd'),
        'env_names': config.get('EnvNames'), 'apparmor': container.get('AppArmorProfile'),
        'owner_label': labels_.get('ai.openhands.runtime-owner'),
        'mounts': [list(m) for m in effective_container_mounts(container)],
        # Moby reports Binds in no fixed order across a reprovision (observed): compared as a set
        'host': {k: sorted(host.get(k) or []) if k == 'Binds' else host.get(k)
                 for k in DRILL_SHAPE_HOST}})


def shape_diff(a, b, path=''):
    """Paths where two shapes differ."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            out += shape_diff(a.get(k), b.get(k), f'{path}.{k}' if path else k)
        return out
    return [] if a == b else [{'field': path, 'baseline': a, 'observed': b}]


def server_view(api, conversation_id):
    base = f'/api/conversations/{conversation_id}'
    info, noauth, conv, runtime = _call(
        api, {'method': 'GET', 'path': '/server_info', 'auth': False},
        {'method': 'GET', 'path': base, 'auth': False},
        {'method': 'GET', 'path': base}, {'method': 'GET', 'path': base + '/runtime'})
    body = conv.get('body') if isinstance(conv.get('body'), dict) else {}
    server = info.get('body') if isinstance(info.get('body'), dict) else {}
    workspace = body.get('workspace') if isinstance(body.get('workspace'), dict) else {}
    return {'conversation_runtime': server.get('conversation_runtime'),
            'available_runtimes': server.get('available_conversation_runtimes'),
            'unauthenticated_status': noauth.get('status'),
            'conversation_status': conv.get('status'),
            'state': {k: body.get(k) for k in ('id', 'execution_status', 'title', 'tags')},
            'workspace': {k: workspace.get(k) for k in ('kind', 'working_dir')},
            'runtime': runtime.get('body') if isinstance(runtime.get('body'), dict) else
            {'status': runtime.get('status')}}


# What the outer server logs when it resumes a stored conversation in its own process (the
# 1.60.1 local runtime path: ConversationService.__aenter__ hydrates a RUNNING record;
# EventService.start creates the stored working directory and initializes git there), observed
# on the drill guests. The journal lines wrap, so these are fragments of single lines.
RESUME_MARKERS = ('Resumed conversation', 'error_recovering_runni', 'Failed to initialize git',
                  'Confirmation policy set')


def restart_summary(detail):
    """A server-restart result for the record: the journal of the new invocation in full only
    when the restart failed or the unit is not active, else only its resume lines."""
    unit = (detail or {}).get('unit') or {}
    lines = ((detail or {}).get('invocation') or {}).get('lines') or []
    failed = (detail or {}).get('rc') != 0 or unit.get('ActiveState') != 'active'
    return {'rc': (detail or {}).get('rc'), 'seconds': (detail or {}).get('seconds'),
            'stderr': (detail or {}).get('stderr'), 'failed': failed,
            'unit': {k: unit.get(k) for k in ('ActiveState', 'SubState', 'Result', 'NRestarts',
                                              'ExecMainStatus')},
            'journal': lines if failed else [line for line in lines
                                             if any(m in str(line) for m in RESUME_MARKERS)]}


def restart_server(req):
    """server-restart; a failed start is retried once (the first failure stays in the record:
    an alteration that stops the server starting fails twice)."""
    first = restart_summary(_detail(req('server-restart')))
    if not first['failed']:
        return first
    retry = restart_summary(_detail(req('server-restart')))
    return dict(retry, first_attempt=first)


def journal_hints(obs, hex_id=None, conversation_id=None):
    """The outer server's resume lines in its current invocation (this start only)."""
    lines = ((obs or {}).get('server_invocation') or {}).get('lines')
    if lines is None:
        lines = ((obs or {}).get('journal') or {}).get(DRILL_SERVER_UNIT) or []
    return [line for line in lines if any(m in str(line) for m in RESUME_MARKERS)]


def state_cycle_verdict(baseline, cycle, marker):
    """(verdict, rows) for one cycle against the baseline cycle: 'steered' when the runtime, the
    image, the mounts, the caps, the working directory or the key handling changed; 'unknown'
    when no container came up to compare (and nothing else changed); else 'unchanged'."""
    rows = []
    shape = cycle.get('shape')
    shape_changes = shape_diff(baseline.get('shape'), shape) if shape is not None else None
    rows.append(check_row('container shape unchanged (image, mounts, caps, user, working_dir, '
                          'runtime options)', shape is None or not shape_changes,
                          shape_changes if shape is not None else 'no container (not observed)'))
    keys_b, keys_c = baseline.get('container_keys'), cycle.get('container_keys')
    rows.append(check_row('the container keys are the conversation identity\'s (key handling)',
                          shape is None or keys_c == keys_b, {'baseline': keys_b, 'observed': keys_c}))
    view_b, view_c = baseline.get('view') or {}, cycle.get('view') or {}
    rows.append(check_row('server runtime docker, not selectable',
                          view_c.get('conversation_runtime') == 'docker' and
                          not view_c.get('available_runtimes'),
                          {k: view_c.get(k) for k in ('conversation_runtime', 'available_runtimes')}))
    rows.append(check_row('unauthenticated request refused (key handling)',
                          view_c.get('unauthenticated_status') == 401,
                          view_c.get('unauthenticated_status')))
    rows.append(check_row('the outer server did not resume the conversation in its own process '
                          '(runtime: its journal at this start)', not cycle.get('journal'),
                          cycle.get('journal')))
    procs_b = sorted(p.get('comm') for p in baseline.get('server_processes') or [])
    procs_c = sorted(p.get('comm') for p in cycle.get('server_processes') or [])
    rows.append(check_row('no new process in the Agent Server unit (no local runtime)',
                          procs_c == procs_b, {'baseline': procs_b, 'observed': procs_c}))
    if marker:
        state = ((cycle.get('marker') or {}).get(marker) or {}).get('state')
        rows.append(check_row('the altered path was not created (working_dir, mounts)',
                              state == 'absent', {marker: state}))
    if not all(r['ok'] for r in rows):
        return 'steered', rows
    if cycle.get('quarantined'):
        return 'quarantined', rows
    return ('unknown' if shape is None else 'unchanged'), rows


def quiesce_summary(req):
    """The quiesce step's summary of the server's last start (slice (c)), or None when the
    guest has no quiesce step (slice (b)'s tooling against an older seed)."""
    result = req('start-window')
    if not result.get('ok'):
        return None
    return ((result.get('detail') or {}).get('last_run') or {}).get('summary')


def quarantined_reason(summary, hex_id):
    for entry in (summary or {}).get('quarantined') or []:
        if isinstance(entry, dict) and entry.get('id') == hex_id:
            return entry.get('reason') or 'quarantined'
    return None


def drill_stored_state(ctx, name, steps, chan, limit=None):
    """Proof item 2: every field of the job-writable stored state altered alone, then a server
    restart (the startup path) and a reopen; the created container must not change."""
    cid = DRILL_IDS['state']
    hex_id = cid.replace('-', '')
    base = f'/api/conversations/{cid}'
    memo = {'cycles': []}

    def observe(paths=()):
        return _detail(chan()[2]('observe', {'paths': list(paths), 'journal_lines': 60}))

    def look(facts):
        report = facts()
        mine = [c for c in report.get('containers') or [] if conversation_hex(c) == hex_id]
        return report, (mine[0] if mine else None)

    def cycle(label, alteration=None):
        api, facts, req = chan()
        entry = {'label': label, 'alteration': alteration}
        applied = []
        ops = alteration.get('combination') if alteration and 'combination' in alteration else \
            ([alteration] if alteration else [])
        try:
            for op in ops:
                params = {'hex': hex_id, 'file': op['file'], 'op': op['op'],
                          'pointer': op.get('pointer'), 'value': op.get('value')}
                result = req('state-alter', params)
                applied.append({k: result.get(k) for k in ('ok', 'error')} |
                               {'detail': result.get('detail')})
                if not result.get('ok'):
                    raise Refused('DRILL', f'state-alter: {result.get("error")}')
            entry['applied'] = applied
            entry['restart'] = restart_server(req)
            entry['quiesce'] = quiesce_summary(req)
            entry['quarantined'] = quarantined_reason(entry['quiesce'], hex_id)
            marker = (alteration or {}).get('marker')
            obs = observe([marker] if marker else [])
            entry['server_processes'] = (obs.get('agent_server') or {}).get('processes') or []
            entry['journal'] = journal_hints(obs, hex_id, cid)
            entry['view'] = server_view(api, cid)
            if entry['quarantined']:
                # slice (c): the quiesce step moved the record aside before the server started;
                # a reopen would make Moby create an empty bind source, so none is sent
                entry['marker'] = obs.get('paths')
                return entry
            reopened, = _call(api, {'method': 'POST', 'path': base + '/runtime/reprovision',
                                    'timeout': 600})
            entry['reopen'] = {k: reopened.get(k) for k in ('status', 'seconds', 'body')}
            report, mine = look(facts)
            entry['shape'] = container_shape(mine) if mine else None
            obs2 = observe([marker] if marker else [])
            entry['container_keys'] = next(iter((obs2.get('containers') or {}).values()), {}).get('keys') \
                if len(obs2.get('containers') or {}) == 1 else None
            entry['marker'] = obs2.get('paths')
            entry['view_after_reopen'] = server_view(api, cid)
        finally:
            if entry.get('quarantined'):
                entry['returned'] = _detail(req('quarantine-return', {'hex': hex_id}))
            entry['rollback'] = rollback(api, req)
        return entry

    def rollback(api, req):
        """Stop the runtime, put the snapshot back, restart the server (which drops anything it
        hydrated in memory and stops its lease renewal), put the snapshot back again (what the
        shutdown wrote), and read the directory."""
        stopped, = _call(api, {'method': 'DELETE', 'path': base + '/runtime', 'timeout': 300})
        first = _detail(req('state-rollback', {'hex': hex_id}))
        restart = restart_server(req)
        second = _detail(req('state-rollback', {'hex': hex_id}))
        files = _detail(req('state-read', {'hex': hex_id}))
        return {'stop': stopped.get('status'),
                'first': {k: first.get(k) for k in ('removed', 'rewritten', 'equal')},
                'restart': restart,
                'second': {k: second.get(k) for k in ('removed', 'rewritten', 'equal')},
                'files': {e['path']: e.get('sha256') for e in files.get('entries') or []
                          if e.get('kind') == 'file'}}

    def setup():
        api, facts, req = chan()
        created, = _call(api, {'method': 'POST', 'path': '/api/conversations',
                               'json': drill_body(ctx, cid), 'timeout': 600})
        if not _status_ok(created):
            return False, {'create': created}
        stopped, = _call(api, {'method': 'DELETE', 'path': base + '/runtime', 'timeout': 300})
        files = _detail(req('state-read', {'hex': hex_id}))
        snapshot = _detail(req('state-snapshot', {'hex': hex_id}))
        memo['files'] = files
        memo['original'] = snapshot.get('files')
        memo['alterations'] = state_alterations(files.get('content') or {})
        return _status_ok(stopped), {'create': {k: created.get(k) for k in ('status', 'seconds')},
                                     'stored_files': files.get('entries'),
                                     'content': files.get('content'), 'snapshot': snapshot,
                                     'alterations': len(memo['alterations'])}

    def restored(entry):
        rb = entry.get('rollback') or {}
        return (rb.get('second') or {}).get('equal') is True and rb.get('files') == memo['original']

    def baseline(label):
        entry = cycle(label)
        memo['cycles'].append(entry)
        ok = entry.get('shape') is not None and entry.get('reopen', {}).get('status') == 200 and \
            restored(entry)
        if ok and 'baseline' not in memo:
            memo['baseline'] = entry
        same = shape_diff(memo['baseline']['shape'], entry['shape']) if ok else None
        return ok and not same, {'cycle': entry, 'differences_from_first_baseline': same}

    def sensitivity():
        """The comparison's own control: a conversation created with request container
        options (the upstream override, decision 0001 s3) must show as a shape change."""
        api, facts, _ = chan()
        sid = DRILL_IDS['state-sensitivity']
        body = drill_body(ctx, sid)
        body['container'] = dict(body.get('container') or {}, memory='2g', cpus=1.0)
        created, = _call(api, {'method': 'POST', 'path': '/api/conversations', 'json': body,
                               'timeout': 600})
        report = facts()
        mine = [c for c in report.get('containers') or [] if conversation_hex(c) == sid.replace('-', '')]
        deleted, = _call(api, {'method': 'DELETE', 'path': f'/api/conversations/{sid}', 'timeout': 300})
        shape = container_shape(mine[0]) if mine else None
        diff = shape_diff(memo['baseline']['shape'], shape) if shape else None
        fields = sorted({d['field'] for d in diff or []})
        return bool(diff) and any(f.startswith('host.Memory') or f.startswith('host.NanoCpus')
                                  for f in fields), {
            'create': created.get('status'), 'delete': deleted.get('status'), 'detected': fields}

    def job_written(kill_inner):
        """The startup pair written by the job itself, from inside its container (uid 999, its
        own conversation-store bind), while its runtime runs; then the runtime is stopped
        (``kill_inner``: the job first kills its own inner server, so that no shutdown of that
        server rewrites the files) and the outer server restarts. Does the write survive, and
        does the outer server act on it?"""
        api, facts, req = chan()
        marker = f'{DRILL_MARKER_ROOT}-job-{"kill" if kill_inner else "stop"}'
        reopened, = _call(api, {'method': 'POST', 'path': base + '/runtime/reprovision', 'timeout': 600})
        script = ("import json, os, subprocess\n"
                  f"d = '/var/openhands/conversations/{hex_id}'\n"
                  "b = json.load(open(d + '/base_state.json'))\n"
                  "b['execution_status'] = 'running'\n"
                  "open(d + '/base_state.json', 'w').write(json.dumps(b))\n"
                  "m = json.load(open(d + '/meta.json'))\n"
                  f"m['workspace']['working_dir'] = '{marker}'\n"
                  "open(d + '/meta.json', 'w').write(json.dumps(m))\n"
                  "pids = []\n")
        if kill_inner:
            script += ("for p in os.listdir('/proc'):\n"
                       "    try:\n"
                       "        if p.isdigit() and p != '1' and b'openhands-agent-server' in "
                       "open('/proc/' + p + '/cmdline', 'rb').read():\n"
                       "            pids.append(p)\n"
                       "    except OSError:\n"
                       "        pass\n"
                       "subprocess.Popen(['sh', '-c', 'sleep 1; kill -9 ' + ' '.join(pids)], "
                       "start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n")
        script += "print(json.dumps({'uid': os.getuid(), 'gid': os.getgid(), 'killing': pids}))\n"
        job, = _call(api, {'method': 'POST', 'path': base + '/bash/execute_bash_command',
                           'json': {'command': container_python(script, ''), 'cwd': '/workspace',
                                    'timeout': 60}, 'timeout': 180})
        body = job.get('body') if isinstance(job.get('body'), dict) else {}
        entry = {'kill_inner': kill_inner, 'marker': marker, 'reopen': reopened.get('status'),
                 'job': {'status': job.get('status'), 'exit_code': body.get('exit_code'),
                         'stdout': str(body.get('stdout') or '')[-300:]}}
        try:
            stopped, = _call(api, {'method': 'DELETE', 'path': base + '/runtime', 'timeout': 300})
            entry['stop'] = stopped.get('status')
            after_stop = _detail(req('state-read', {'hex': hex_id}))
            content = after_stop.get('content') or {}
            entry['persisted'] = {
                'execution_status': (content.get('base_state.json') or {}).get('execution_status'),
                'working_dir': ((content.get('meta.json') or {}).get('workspace') or {}).get('working_dir')}
            entry['restart'] = restart_server(req)
            obs = observe([marker])
            entry['paths'] = obs.get('paths')
            entry['journal'] = journal_hints(obs)
            entry['view'] = server_view(api, cid)
            entry['server_processes'] = ((obs.get('agent_server') or {}).get('processes'))
        finally:
            entry['rollback'] = rollback(api, req)
        written = body.get('exit_code') == 0
        created = ((entry.get('paths') or {}).get(marker) or {}).get('state') not in (None, 'absent')
        entry['summary'] = {'job_wrote': written,
                            'execution_status_survived': (entry.get('persisted') or {}).get(
                                'execution_status') == 'running',
                            'working_dir_survived': (entry.get('persisted') or {}).get('working_dir') == marker,
                            'outer_server_resumed_it': bool(entry.get('journal')),
                            'outer_server_created_the_working_dir': created}
        # steering by the job alone is a FAIL: the step passes only if the outer server did not act
        return written and not entry['journal'] and not created and restored(entry), entry

    def alterations():
        rows, steering, unknown, quarantined = [], [], [], []
        todo = memo['alterations'][:limit] if limit is not None else memo['alterations']
        for alt in todo:
            log(f'drill stored-state: alteration {alt["n"] + 1}/{len(todo)}')
            try:
                entry = cycle(f'alteration {alt["n"]}', alt)
                verdict, checks = state_cycle_verdict(memo['baseline'], entry, alt.get('marker'))
                back = restored(entry)
            except DrillSteps.CAUGHT as exc:
                entry, verdict, checks, back = {'error': f'{type(exc).__name__}: {exc}'}, 'unknown', [], False
            row = {'n': alt['n'], 'alteration': alt, 'verdict': verdict,
                   'steered': verdict == 'steered', 'checks': checks, 'restored': back,
                   'cycle': entry}
            rows.append(row)
            if verdict == 'steered':
                steering.append(alt['n'])
            elif verdict == 'quarantined':
                quarantined.append(alt['n'])
            elif verdict == 'unknown':
                unknown.append(alt['n'])
            if not back:
                steps.broken = f'alteration {alt["n"]} was not rolled back'
                break
        memo['rows'] = rows
        return not steering and not unknown and all(r['restored'] for r in rows), {
            'alterations': len(todo), 'run': len(rows), 'steering': steering, 'unknown': unknown,
            'quarantined': quarantined,
            'rewritten_by_quiesce': [r['n'] for r in rows if hex_id in
                                     (((r.get('cycle') or {}).get('quiesce') or {}).get('rewritten') or [])],
            'rows': rows}

    steps.run('create, stop and read the stored conversation', setup)
    steps.run('baseline cycle (restart and reopen, nothing altered)', lambda: baseline('baseline'))
    steps.run('comparison sensitivity (request caps differ)', sensitivity)
    steps.run('every stored field altered alone, then restart and reopen', alterations)
    steps.run('the job itself writes the startup pair, then its runtime stops and the server '
              'restarts', lambda: job_written(False))
    steps.run('the job itself writes the startup pair and kills its own inner server, then the '
              'server restarts', lambda: job_written(True))
    steps.run('closing baseline cycle', lambda: baseline('closing baseline'))

    def cleanup():
        api, _, req = chan()
        discarded = req('state-discard', {'hex': hex_id})
        deleted, = _call(api, {'method': 'DELETE', 'path': base, 'timeout': 300})
        return deleted.get('status') == 200 and discarded.get('ok'), {
            'delete': deleted.get('status'), 'snapshot_discarded': discarded.get('detail')}
    steps.run('delete the drill conversation', cleanup, always=True)
    return memo


# ---------------------------------------------------------------- F-2 closed (slice (c))

F2_HOME = '/srv/scratch/openhands/home'
F2_REMOVAL_ACTIONS = ('destroy', 'die', 'kill', 'stop')
F2_RULE = ('FAIL on any of: a Resumed conversation, error_recovering_running_conversation or '
           "Confirmation policy set to line in the server's start invocation; an "
           'owner_lease.json written by the outer server; any path created outside the '
           "conversation's three binds and the declared stores (in particular under "
           f'{F2_HOME}); execution_status running surviving the quiesce step; any container '
           "event between the step's end and the server's ExecStart, or a container left by "
           "the step; the quiesce unit's result not success while the server is active. PASS "
           'only when every variant passes with its control.')


def _file_shas(state):
    return {e['path']: e.get('sha256') for e in (state or {}).get('entries') or []
            if e.get('kind') == 'file'}


def _record_paths(state):
    return sorted(e['path'] for e in (state or {}).get('entries') or [])


def f2_rule_rows(hex_id, window, obs, before, after, home_before, marker=None, record_paths=True):
    """The F-2 closed decision rule for one server start (fixed before observation)."""
    last = ((window or {}).get('last_run') or {}).get('summary') or {}
    events = (window or {}).get('events') or {}
    between = events.get('quiesce_exit_to_server_exec_start')
    q_unit, s_unit = (window or {}).get('quiesce_unit') or {}, (window or {}).get('server_unit') or {}
    times = (window or {}).get('times') or {}
    lease_b = _file_shas(before).get('owner_lease.json')
    lease_a = _file_shas(after).get('owner_lease.json') if after is not None else lease_b
    home_now = (((obs or {}).get('paths') or {}).get(F2_HOME) or {}).get('entries')
    status = (((after or {}).get('content') or {}).get('base_state.json') or {}).get('execution_status') \
        if after is not None else None
    rows = [
        check_row('no resume line in the server\'s start invocation', not journal_hints(obs),
                  journal_hints(obs)),
        check_row('no owner_lease.json written by the outer server', lease_a == lease_b,
                  {'before': lease_b, 'after': lease_a}),
        check_row(f'no new path under {F2_HOME}', home_now is not None and home_now == home_before,
                  {'before': home_before, 'after': home_now}),
        check_row('execution_status running did not survive the quiesce step', status != 'running',
                  status if after is not None else 'record moved aside (quarantine)'),
        check_row("no container between the step's end and the server's ExecStart; none left by "
                  'the step', isinstance(between, list) and not between and
                  last.get('containers_remaining') == 0 and
                  bool(times.get('quiesce_exit')) and bool(times.get('server_exec_start')) and
                  times['quiesce_exit'] <= times['server_exec_start'],
                  {'events': between, 'containers_remaining': last.get('containers_remaining'),
                   'times': times}),
        check_row('the quiesce unit succeeded while the server is active',
                  q_unit.get('Result') == 'success' and last.get('ok') is True and
                  s_unit.get('ActiveState') == 'active',
                  {'quiesce': q_unit.get('Result'), 'summary_ok': last.get('ok'),
                   'server': s_unit.get('ActiveState')}),
    ]
    if marker:
        state = (((obs or {}).get('paths') or {}).get(marker) or {}).get('state')
        rows.append(check_row('the stored working directory was not created', state == 'absent',
                              {marker: state}))
    if record_paths and after is not None:
        rows.append(check_row('no new path in the record directory', set(_record_paths(after)) <=
                              set(_record_paths(before)),
                              sorted(set(_record_paths(after)) - set(_record_paths(before)))))
    return rows


def drill_f2_closed(ctx, name, steps, chan, reboot):
    """E-01.2.2 slice (c): the 'F-2 closed' drill. Variants A (the helper writes the start-up
    pair), B1 (the job writes it; the runtime stops normally), B2 (the job writes it; root
    force-kills the container), C (the job rewrites it in a loop while the server restarts with
    its container alive), D (an idle record is retained), F (a record claims another
    conversation's id), G (base_state.json a symbolic link, a hard link). Variant E (the step
    itself fails) is part of the fail-closed drill."""
    memo = {'rule': F2_RULE, 'variants': {}}

    def observe(paths=()):
        return _detail(chan()[2]('observe', {'paths': [F2_HOME] + list(paths), 'journal_lines': 60}))

    def home_entries():
        return ((observe().get('paths') or {}).get(F2_HOME) or {}).get('entries')

    def read(hex_id):
        return _detail(chan()[2]('state-read', {'hex': hex_id}))

    def create(key, stop=True):
        api, _, _ = chan()
        cid = DRILL_IDS[key]
        created, = _call(api, {'method': 'POST', 'path': '/api/conversations',
                               'json': drill_body(ctx, cid), 'timeout': 600})
        if not _status_ok(created):
            raise Refused('DRILL', f'create {key}: {created.get("status")} {created.get("error")}')
        stopped = None
        if stop:
            stopped, = _call(api, {'method': 'DELETE', 'path': f'/api/conversations/{cid}/runtime',
                                   'timeout': 300})
        return cid, cid.replace('-', ''), {'create': created.get('status'),
                                           'stop': (stopped or {}).get('status')}

    def started(req, how='restart'):
        """One server start (systemctl restart, or the server killed and restarted by systemd),
        then the start's order and the server's journal of that start."""
        detail = _detail(req('server-kill' if how == 'kill' else 'server-restart'))
        return restart_summary(detail), _detail(req('start-window'))

    def job_writes(api, cid, hex_id, marker, loop=False):
        """The job, from inside its own container (uid 999, its conversation-store bind), writes
        the start-up pair once, or starts a detached loop that rewrites it every 0.2 s."""
        write = ("import json, time\n"
                 f"d = '/var/openhands/conversations/{hex_id}'\n"
                 "def pair():\n"
                 "    b = json.load(open(d + '/base_state.json'))\n"
                 "    b['execution_status'] = 'running'\n"
                 "    open(d + '/base_state.json', 'w').write(json.dumps(b))\n"
                 "    m = json.load(open(d + '/meta.json'))\n"
                 f"    m['workspace']['working_dir'] = '{marker}'\n"
                 "    open(d + '/meta.json', 'w').write(json.dumps(m))\n")
        if loop:
            body = write + ("end = time.time() + 900\n"
                            "while time.time() < end:\n"
                            "    try:\n"
                            "        pair()\n"
                            "    except (OSError, ValueError):\n"
                            "        pass\n"
                            "    time.sleep(0.2)\n")
            script = ("import base64, os, subprocess, sys\n"
                      f"code = base64.b64decode('{base64.b64encode(body.encode()).decode()}').decode()\n"
                      "p = subprocess.Popen([sys.executable, '-c', code], start_new_session=True,\n"
                      "                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
                      "print('{\"loop_pid\": %d, \"uid\": %d}' % (p.pid, os.getuid()))\n")
        else:
            script = write + "pair()\nimport os\nprint('{\"uid\": %d, \"gid\": %d}' % (os.getuid(), os.getgid()))\n"
        job, = _call(api, {'method': 'POST', 'path': f'/api/conversations/{cid}/bash/execute_bash_command',
                           'json': {'command': container_python(script, ''), 'cwd': '/workspace',
                                    'timeout': 60}, 'timeout': 180})
        body = job.get('body') if isinstance(job.get('body'), dict) else {}
        return {'status': job.get('status'), 'exit_code': body.get('exit_code'),
                'stdout': str(body.get('stdout') or '')[-300:]}

    def verdict(rows, extra):
        rows = rows + extra
        return all(r['ok'] for r in rows), rows

    def cleanup(*keys):
        api, _, req = chan()
        out = {}
        for key in keys:
            cid = DRILL_IDS[key]
            deleted, = _call(api, {'method': 'DELETE', 'path': f'/api/conversations/{cid}',
                                   'timeout': 300})
            out[key] = deleted.get('status')
            req('state-discard', {'hex': cid.replace('-', '')})
        return out

    def variant_a():
        cid, hex_id, made = create('f2-a')
        api, _, req = chan()
        marker = f'{DRILL_MARKER_ROOT}-f2-a'
        home0 = home_entries()
        _detail(req('state-snapshot', {'hex': hex_id}))
        for op in ({'file': 'base_state.json', 'pointer': ['execution_status'], 'value': 'running'},
                   {'file': 'meta.json', 'pointer': ['workspace', 'working_dir'], 'value': marker}):
            _detail(req('state-alter', dict(op, hex=hex_id, op='set')))
        before = read(hex_id)
        restart, window = started(req)
        obs = observe([marker])
        after = read(hex_id)
        summary = ((window.get('last_run') or {}).get('summary') or {})
        ok, rows = verdict(f2_rule_rows(hex_id, window, obs, before, after, home0, marker), [
            check_row('the step rewrote this record (running to error)',
                      hex_id in (summary.get('rewritten') or []), summary.get('rewritten'))])
        view = server_view(api, cid)
        return ok, {'made': made, 'restart': restart, 'window': window, 'checks': rows,
                    'view': view, 'cleanup': cleanup('f2-a')}

    def variant_b(kill):
        key = 'f2-b2' if kill else 'f2-b1'
        cid, hex_id, made = create(key, stop=False)
        api, _, req = chan()
        marker = f'{DRILL_MARKER_ROOT}-{key}'
        home0 = home_entries()
        job = job_writes(api, cid, hex_id, marker)
        if kill:
            stop = _detail(req('container-kill', {'hex': hex_id}))
        else:
            stopped, = _call(api, {'method': 'DELETE', 'path': f'/api/conversations/{cid}/runtime',
                                   'timeout': 300})
            stop = {'status': stopped.get('status')}
        before = read(hex_id)
        persisted = {'execution_status': ((before.get('content') or {}).get('base_state.json') or {})
                     .get('execution_status'),
                     'working_dir': (((before.get('content') or {}).get('meta.json') or {})
                                     .get('workspace') or {}).get('working_dir')}
        restart, window = started(req)
        obs = observe([marker])
        after = read(hex_id)
        summary = ((window.get('last_run') or {}).get('summary') or {})
        wd_after = (((after.get('content') or {}).get('meta.json') or {}).get('workspace') or {}) \
            .get('working_dir')
        extra = [check_row('the job wrote the pair (exit 0, as uid 999)', job.get('exit_code') == 0,
                           job),
                 check_row('running persisted after the stop (what the step must neutralize)',
                           persisted['execution_status'] == 'running', persisted),
                 check_row('the step rewrote this record (running to error)',
                           hex_id in (summary.get('rewritten') or []), summary.get('rewritten'))]
        if kill:
            extra += [check_row('the container was force-killed (no inner shutdown)',
                                bool(stop.get('containers')) and not stop.get('remaining'), stop),
                      check_row('the working_dir text survives in meta.json (the kill-race case)',
                                persisted['working_dir'] == marker and wd_after == marker,
                                {'after_kill': persisted['working_dir'], 'after_start': wd_after})]
        ok, rows = verdict(f2_rule_rows(hex_id, window, obs, before, after, home0, marker,
                                        record_paths=False), extra)
        return ok, {'made': made, 'job': job, 'stop': stop, 'persisted': persisted,
                    'restart': restart, 'window': window, 'checks': rows,
                    'view': server_view(api, cid), 'cleanup': cleanup(key)}

    def variant_c():
        cid, hex_id, made = create('f2-c', stop=False)
        api, _, req = chan()
        marker = f'{DRILL_MARKER_ROOT}-f2-c'
        home0 = home_entries()
        job = job_writes(api, cid, hex_id, marker, loop=True)
        before, _ = wait_until(lambda: read(hex_id), lambda s: (((s.get('content') or {})
                               .get('base_state.json') or {}).get('execution_status') == 'running'), 30)
        runs0 = _detail(req('start-window')).get('runs_this_boot')
        restart, window = started(req, 'kill')
        obs = observe([marker])
        after = read(hex_id)
        summary = ((window.get('last_run') or {}).get('summary') or {})
        events = window.get('events') or {}
        cleanup_events = [e for e in events.get('server_exec_start_to_active') or []
                          if e.get('action') in F2_REMOVAL_ACTIONS]
        removed = [e for e in events.get('during_quiesce') or [] if e.get('action') == 'destroy']
        extra = [check_row('the job started its rewrite loop', job.get('exit_code') == 0, job),
                 check_row('systemd restarted the killed server and ran the step again',
                           (window.get('runs_this_boot') or 0) > (runs0 or 0) and
                           int((restart.get('unit') or {}).get('NRestarts') or 0) >= 1,
                           {'runs_before': runs0, 'runs_after': window.get('runs_this_boot'),
                            'unit': restart.get('unit')}),
                 check_row('the step removed the live container (containers removed >= 1)',
                           (summary.get('containers_removed') or 0) >= 1,
                           summary.get('containers_removed')),
                 check_row('the step rewrote this record (records rewritten >= 1)',
                           hex_id in (summary.get('rewritten') or []), summary.get('rewritten')),
                 check_row("the server's own start-up cleanup found 0 (no removal event from its "
                           'ExecStart to active)', isinstance(events.get('server_exec_start_to_active'), list)
                           and not cleanup_events, events.get('server_exec_start_to_active')),
                 check_row('control: the event method sees the step\'s removal (destroy during '
                           'the step)', bool(removed), events.get('during_quiesce'))]
        ok, rows = verdict(f2_rule_rows(hex_id, window, obs, before, after, home0, marker,
                                        record_paths=False), extra)
        return ok, {'made': made, 'job': job, 'restart': restart, 'window': window,
                    'checks': rows, 'view': server_view(api, cid), 'cleanup': cleanup('f2-c')}

    def variant_d():
        cid, hex_id, made = create('f2-d')
        api, _, req = chan()
        home0 = home_entries()

        def hashes():
            s = _file_shas(read(hex_id))
            return {k: s.get(k) for k in ('base_state.json', 'meta.json')}
        h_stop = hashes()
        before = read(hex_id)
        restart, window = started(req)
        obs = observe()
        after = read(hex_id)
        h_restart = hashes()
        summary = ((window.get('last_run') or {}).get('summary') or {})
        reopened, = _call(api, {'method': 'POST', 'path': f'/api/conversations/{cid}/runtime/reprovision',
                                'timeout': 600})
        h_reopen = hashes()
        boots = reboot()
        settled, _ = wait_until(observe, lambda o: _settled(o) and
                                _unit(o, DRILL_SERVER_UNIT).get('ActiveState') == 'active', DRILL_SETTLE_S)
        api, _, req = chan()
        h_boot = hashes()
        listed, got = _call(api, {'method': 'GET', 'path': '/api/conversations/search?limit=50'},
                            {'method': 'GET', 'path': f'/api/conversations/{cid}'})
        ids = [i.get('id') for i in ((listed.get('body') or {}).get('items') or [])
               if isinstance(i, dict)]
        extra = [check_row('base_state.json and meta.json sha256 unchanged across the restart, the '
                           'reopen and the guest restart (F-04.2 retention)',
                           h_stop == h_restart == h_reopen == h_boot and all(h_stop.values()),
                           {'stopped': h_stop, 'restart': h_restart, 'reopen': h_reopen,
                            'guest_restart': h_boot}),
                 check_row('the step left the idle record unchanged',
                           hex_id not in (summary.get('rewritten') or []) and
                           not quarantined_reason(summary, hex_id), summary),
                 check_row('reopen 200', reopened.get('status') == 200, reopened.get('status')),
                 check_row('listed and readable after the guest restart',
                           cid in ids and got.get('status') == 200,
                           {'listed': cid in ids, 'get': got.get('status')})]
        ok, rows = verdict(f2_rule_rows(hex_id, window, obs, before, after, home0), extra)
        return ok, {'made': made, 'restart': restart, 'window': window, 'reboot': boots,
                    'checks': rows, 'cleanup': cleanup('f2-d')}

    def variant_f():
        real, real_hex, made_r = create('f2-f-real')
        foreign, foreign_hex, made_f = create('f2-f-foreign')
        api, _, req = chan()
        home0 = home_entries()
        title = 'aieh-drill-foreign-record'
        _detail(req('state-snapshot', {'hex': foreign_hex}))
        for pointer, value in ((['id'], real), (['title'], title)):
            _detail(req('state-alter', {'hex': foreign_hex, 'file': 'meta.json', 'op': 'set',
                                        'pointer': pointer, 'value': value}))
        before_real = read(real_hex)
        restart, window = started(req)
        obs = observe([f'/srv/scratch/openhands/conversations/{foreign_hex}'])
        after_real = read(real_hex)
        summary = ((window.get('last_run') or {}).get('summary') or {})
        q = _detail(req('quarantine-list'))
        got, = _call(api, {'method': 'GET', 'path': f'/api/conversations/{real}'})
        body = got.get('body') if isinstance(got.get('body'), dict) else {}
        gone = ((obs.get('paths') or {}).get(f'/srv/scratch/openhands/conversations/{foreign_hex}')
                or {}).get('state')
        extra = [check_row('the foreign-id record was quarantined (id-mismatch)',
                           quarantined_reason(summary, foreign_hex) == 'id-mismatch',
                           summary.get('quarantined')),
                 check_row('it left the conversations path and is in the quarantine',
                           gone == 'absent' and any(e['name'].startswith(foreign_hex + '.')
                                                    for e in q.get('entries') or []),
                           {'conversations_path': gone, 'quarantine': q}),
                 check_row("the real conversation's GET answers from its own record",
                           got.get('status') == 200 and str(body.get('id')).replace('-', '') == real_hex
                           and body.get('title') != title,
                           {'status': got.get('status'), 'id': body.get('id'), 'title': body.get('title')})]
        ok, rows = verdict(f2_rule_rows(real_hex, window, obs, before_real, after_real, home0), extra)
        return ok, {'made': [made_r, made_f], 'restart': restart, 'window': window,
                    'checks': rows, 'cleanup': cleanup('f2-f-real', 'f2-f-foreign')}

    def variant_g(kind):
        key = f'f2-g-{kind}'
        cid, hex_id, made = create(key)
        api, _, req = chan()
        home0 = home_entries()
        planted = _detail(req('sentinel-plant', {'hex': hex_id, 'kind': kind}))
        restart, window = started(req)
        obs = observe([f'/srv/scratch/openhands/conversations/{hex_id}'])
        summary = ((window.get('last_run') or {}).get('summary') or {})
        sentinel = _detail(req('sentinel-check', {'hex': hex_id, 'kind': kind}))
        gone = ((obs.get('paths') or {}).get(f'/srv/scratch/openhands/conversations/{hex_id}')
                or {}).get('state')
        reason = {'symlink': 'link', 'hardlink': 'hard-linked'}[kind]
        extra = [check_row(f'the record was quarantined ({reason})',
                           quarantined_reason(summary, hex_id) == reason and gone == 'absent',
                           {'quarantined': summary.get('quarantined'), 'conversations_path': gone}),
                 check_row('the planted link was in place before the start',
                           planted.get('base_is_link') if kind == 'symlink' else
                           planted.get('base_nlink') == 2, planted),
                 check_row('nothing outside the record was read (atime) or written (mtime, ctime, '
                           'size, sha256)', sentinel.get('unread') is True and
                           sentinel.get('unwritten') is True and sentinel.get('sha256_equal') is True,
                           {k: sentinel.get(k) for k in ('unread', 'unwritten', 'sha256_equal',
                                                         'record', 'now')}),
                 check_row('control: a read of the sentinel moves its atime',
                           sentinel.get('control_read_moved_atime') is True,
                           sentinel.get('control_read_moved_atime'))]
        ok, rows = verdict(f2_rule_rows(hex_id, window, obs, None, None, home0), extra)
        return ok, {'made': made, 'planted': planted, 'restart': restart, 'window': window,
                    'checks': rows, 'cleanup': cleanup(key)}

    for label, func in (('A: the helper writes the start-up pair', variant_a),
                        ('B1: the job writes the pair; the runtime stops normally',
                         lambda: variant_b(False)),
                        ('B2: the job writes the pair; root force-kills the container',
                         lambda: variant_b(True)),
                        ('C: the job rewrites the pair in a loop; the server restarts with its '
                         'container alive', variant_c),
                        ('D: an idle record is retained (F-04.2)', variant_d),
                        ('F: a record claims another conversation\'s id', variant_f),
                        ('G: base_state.json a symbolic link', lambda: variant_g('symlink')),
                        ('G: base_state.json a hard link', lambda: variant_g('hardlink'))):
        memo['variants'][label] = steps.run(label, func)
    return memo


# ---------------------------------------------------------------- guest-root P5 (proof item 3)

def canary_core_digests(canaries):
    """{label: sha256 hex} of every 32-hex core of the canary set: what the guest searches
    for (the values never travel to the guest)."""
    out = {}
    for label, value in sorted(((canaries or {}).get('needles') or {}).items()):
        for i, core in enumerate(re.findall(r'[0-9a-f]{32}', value)):
            out[f'{label}#{i}'] = hashlib.sha256(core.encode()).hexdigest()
    return out


def instance_key_body_sha256(key_path):
    """sha256 of the per-instance private key's base64 body, whitespace removed."""
    text = Path(key_path).read_text(encoding='ascii')
    body = ''.join(line.strip() for line in text.splitlines()
                   if line.strip() and not line.startswith('-----'))
    return hashlib.sha256(''.join(body.split()).encode('ascii')).hexdigest()


def declared_secret_store(label, path, owners, containers):
    """Whether one place holding a guest secret is a declared store: the server's environment
    file and its processes (profile provisioning.agent_server.secrets), the agent-readable
    session key (.session_key), and for a conversation's own keys Moby's store of that
    container, its runtime state and its own processes (fd-container-shares-service-uid)."""
    kind = label.split(':')
    if len(kind) >= 3 and kind[1] in ('server', 'server-copy'):
        var = kind[2]
        if path == '/etc/aieh/agent-server/secrets.env':
            return 'the server environment file (secrets.env)'
        if var in ('OH_SESSION_API_KEYS_0', 'session.key') and \
                path == '/var/lib/aieh/agent-server/session.key':
            return 'the agent-readable session key file (profiles P5, amended 2026-11-07)'
        owner = owners.get(path) or {}
        if path.endswith('/environ') and str(owner.get('cgroup', '')).endswith(
                '/aieh-agent-server.service'):
            return 'the Agent Server process environment'
        return None
    if len(kind) >= 4 and kind[1] == 'container':
        cid = next((c for c in containers if c.startswith(kind[2])), None)
        if cid is None:
            return None
        if path.startswith(f'/srv/scratch/docker/containers/{cid}/'):
            return "Moby's store of that container (docker inspect)"
        if path.startswith(f'/run/containerd/io.containerd.runtime.v2.task/moby/{cid}/'):
            return "containerd's runtime state of that container"
        if path == CONTAINERD_METADATA:
            return "containerd's metadata store (the container's spec, root-only)"
        owner = owners.get(path) or {}
        if path.endswith(('/environ', '/cmdline')) and cid in str(owner.get('cgroup', '')):
            return "that container's own processes"
        hex_id = containers.get(cid)
        if hex_id and (path.startswith(f'/srv/scratch/openhands/persistence/runtime-data/{hex_id}/') or
                       path.startswith(f'/srv/scratch/openhands/conversations/{hex_id}/')):
            return "that conversation's own (job-readable) storage"
        return None
    return None


CONTAINERD_METADATA = '/var/lib/containerd/io.containerd.metadata.v1.bolt/meta.db'
# Where an Owner-class pattern is expected in a provisioned guest (observed on the first
# official drill guest): upstream content, namely the pinned guest image's and the pinned
# packages' files under /usr (OpenSSH's binaries carry their key armor, cloud-init its example
# keys, gnutls its test keys), Moby's layer store (the pinned conversation image's layers and the
# containers' upper layers, which hold that image's own extraction of the server binary) and the
# outer Agent Server's extraction of the locked release binary in its TMPDIR; the guest's own SSH
# host keys (profiles P5); and the scan's positive control. Anything else is reported.
PATTERN_PLACES = ((re.compile(r'^/usr/'), 'upstream content: the pinned guest image and packages (/usr)'),
                  (re.compile(r'^/srv/scratch/docker/overlay2/[0-9a-f]{64}(-init)?/diff/'),
                   "upstream content: Moby's layer store (the pinned conversation image)"),
                  (re.compile(r'^/srv/scratch/openhands/tmp/_MEI[0-9A-Za-z]+/'),
                   "upstream content: the outer Agent Server's extraction of the locked release binary"),
                  (re.compile(r'^/etc/ssh/ssh_host_[a-z0-9]+_key$'), "the guest's own SSH host keys"),
                  (re.compile(r'^/var/lib/aieh-drill/control/'), "the scan's positive control"))


def pattern_place(path):
    return next((label for rx, label in PATTERN_PLACES if rx.match(path)), None)


def root_scan_verdict(scan, key_sha, containers):
    """(verdict, findings) of the guest-root P5 scan (proof item 3)."""
    hits = scan.get('hits') or {}
    owners = scan.get('process_owners') or {}
    findings, rows = [], []
    control = scan.get('control') or {}
    control_found = [h['path'] for h in hits.get('control:canary') or []]
    secret_control = [h['path'] for h in hits.get('control:secret') or []]
    key_control = [k['path'] for k in scan.get('key_blocks') or []
                   if k.get('body_sha256') == control.get('key_body_sha256')]
    rows.append(check_row('positive control: canary-shaped value found at its path only',
                          control_found == [control.get('path')], control_found))
    rows.append(check_row('positive control: secret value found at its path only',
                          secret_control == [f'{control.get("path")}.secret'], secret_control))
    rows.append(check_row('positive control: private-key block found', key_control == [control.get('path')],
                          key_control))
    rows.append(check_row('the scan completed (every mount, no ceiling)', scan.get('complete') is True,
                          {k: scan.get(k) for k in ('files', 'bytes', 'proc_files', 'seconds')}))
    canary = {k: v for k, v in hits.items() if k.startswith('canary:')}
    rows.append(check_row('no host canary anywhere in the guest', not canary, canary))
    stray, declared = [], {}
    for label, where in sorted(hits.items()):
        if not label.startswith('secret:'):
            continue
        for h in where:
            store = declared_secret_store(label, h['path'], owners, containers)
            if store:
                declared.setdefault(label, []).append({'path': h['path'], 'store': store})
            else:
                stray.append({'label': label, 'path': h['path'], 'count': h['count'],
                              'owner': owners.get(h['path'])})
    rows.append(check_row('every guest secret found only in a declared store', not stray, stray))
    server_found = {lab: [d['store'] for d in v] for lab, v in declared.items()
                    if lab.startswith('secret:server:')}
    rows.append(check_row('the server secrets were found in their declared stores (live control)',
                          any('secrets.env' in s for s in server_found.get('secret:server:OH_SECRET_KEY', []))
                          and any('secrets.env' in s for s in
                                  server_found.get('secret:server:OH_SESSION_API_KEYS_0', [])),
                          server_found))
    leaked_key = [k for k in scan.get('key_blocks') or [] if k.get('body_sha256') == key_sha]
    rows.append(check_row('the per-instance private key is nowhere in the guest', not leaked_key,
                          leaked_key))
    copies = [lab for lab in hits if lab.startswith('secret:server-copy:')]
    rows.append(check_row('no kept copy of the server secrets (key drill restored)', not copies, copies))
    raw_rows = []
    for device, r in sorted((scan.get('raw') or {}).items()):
        mount = r.get('mount', '')
        nested = [m for m in scan.get('mounts_walked') or [] if m != mount and
                  m.startswith(mount.rstrip('/') + '/')]
        for label, n in sorted((r.get('counts') or {}).items()):
            files = sum(h['count'] for h in hits.get(label) or [] if not h['path'].startswith(
                '/proc/') and (h['path'].startswith(mount.rstrip('/') + '/') or h['path'] == mount))
            files -= sum(h['count'] for h in hits.get(label) or [] for m in nested
                         if h['path'].startswith(m.rstrip('/') + '/'))
            raw_rows.append({'device': device, 'mount': mount, 'label': label, 'raw': n,
                             'files': files, 'residue': max(0, n - files)})
    residue_server = [r for r in raw_rows if r['residue'] and
                      r['label'].startswith(('secret:server:', 'canary:'))]
    if scan.get('raw'):
        rows.append(check_row('raw devices: no server secret or canary beyond the files that hold it',
                              not residue_server, residue_server))
    unexplained = [{'class': lab.split(':', 1)[1], 'path': h['path'], 'count': h['count']}
                   for lab, where in sorted(hits.items()) if lab.startswith('owner:')
                   for h in where if not pattern_place(h['path'])]
    rows.append(check_row('Owner-class patterns only in upstream image content or the guest\'s own '
                          'host keys', not unexplained, unexplained))
    ok = all(r['ok'] for r in rows)
    control_ok = all(r['ok'] for r in rows[:3])
    verdict = 'PASS' if ok else ('UNKNOWN' if not control_ok and not canary and not stray
                                 and not leaked_key and not unexplained else 'FAIL')
    patterns = {lab: [{'path': h['path'], 'count': h['count'], 'place': pattern_place(h['path'])}
                      for h in where]
                for lab, where in sorted(hits.items()) if lab.startswith('owner:')}
    return verdict, {'checks': rows, 'declared': declared, 'stray': stray,
                     'raw': raw_rows, 'owner_patterns': patterns,
                     'key_blocks': scan.get('key_blocks')}


def drill_root_scan(ctx, name, idir, steps, chan, canaries, raw):
    memo = {}

    def scan():
        api, facts, req = chan()
        report = facts()
        containers = {c.get('Id'): conversation_hex(c) for c in report.get('containers') or []}
        params = {'canary_core_sha256': canary_core_digests(canaries), 'raw': bool(raw),
                  'max_seconds': DRILL_SCAN_CEILING_S - 120}
        result = req('root-scan', params, ceiling=DRILL_SCAN_CEILING_S)
        data = _detail(result)
        verdict, detail = root_scan_verdict(data, instance_key_body_sha256(idir / 'ssh' / 'id_ed25519'),
                                            containers)
        memo['verdict'] = verdict
        return verdict == 'PASS', {'verdict': verdict, 'containers': containers,
                                   'canaries': canary_summary(canaries['needles']) if canaries else None,
                                   'canary_cores': len(params['canary_core_sha256']),
                                   'scan': {k: data.get(k) for k in (
                                       'mounts_walked', 'files', 'bytes', 'proc_files', 'errors',
                                       'complete', 'seconds', 'secrets', 'control')},
                                   'secret_occurrences_redacted': result.get('secret_occurrences_redacted'),
                                   **detail}

    def with_conversation():
        """A running conversation, so its container and keys are in the scan."""
        api, facts, _ = chan()
        created, = _call(api, {'method': 'POST', 'path': '/api/conversations',
                               'json': drill_body(ctx, DRILL_IDS['control']), 'timeout': 600})
        return _status_ok(created), {'create': {k: created.get(k) for k in ('status', 'seconds')}}

    def cleanup():
        api, _, _ = chan()
        deleted, = _call(api, {'method': 'DELETE', 'path': f'/api/conversations/{DRILL_IDS["control"]}',
                               'timeout': 300})
        return deleted.get('status') == 200, {'delete': deleted.get('status')}

    steps.run('create a conversation (its container and keys are scanned)', with_conversation)
    steps.run('guest-root P5 scan', scan)
    steps.run('delete the conversation', cleanup, always=True)
    return memo


# ---------------------------------------------------------------- the admitted create, live

def admitted_container_check(profile, record, report, admitted, sent_sha256):
    """The created container against the admitted create (slice (a)'s AdmittedCreate.to_json):
    its mounts equal the admitted mount set exactly, its caps equal the admitted caps (the
    profile's, the body sends none), its runtime is the server's Docker runtime (a container
    exists for the conversation, the image is the locked one), and the body sent is the
    admitted body: ``sent_sha256``, the dispatch transport's record of the create (the sha256
    of its canonical body, guest_transport.body_sha256), equals the admitted body's."""
    hex_id = str(admitted.get('conversation_id', '')).replace('-', '')
    mine = [c for c in report.get('containers') or [] if conversation_hex(c) == hex_id]
    cfg = (provisioning_config(profile)['agent_server'].get('config') or {}).get('content') or {}
    rows = [check_row('one container for the admitted conversation', len(mine) == 1, len(mine))]
    c = mine[0] if mine else {}
    host = c.get('HostConfig') or {}
    want = sorted(('bind', m['source'], m['destination'], bool(m['rw'])) for m in admitted.get('mounts') or [])
    rows.append(check_row('mounts equal the admitted mount set', effective_container_mounts(c) == want,
                          {'admitted': [list(m) for m in want],
                           'container': [list(m) for m in effective_container_mounts(c)]}))
    container_opts = (admitted.get('body') or {}).get('container') or {}
    # the caps the attempt was admitted under (the reserved policy's, when the driver gives
    # them; else the profile's configuration), unless the admitted body itself sends a cap
    policy = admitted.get('admission_caps') or {
        'memory': cfg.get('conversation_container_memory'),
        'cpus': cfg.get('conversation_container_cpus'),
        'pids_limit': cfg.get('conversation_container_pids_limit')}
    want_caps = {'Memory': memory_bytes(container_opts.get('memory') or policy.get('memory')),
                 'NanoCpus': int(round(float(container_opts.get('cpus') or
                                             policy.get('cpus') or 0) * 1e9)),
                 'PidsLimit': policy.get('pids_limit')}
    got_caps = {k: host.get(k) for k in want_caps}
    rows.append(check_row('caps equal the admitted ones', got_caps == want_caps,
                          {'admitted': want_caps, 'container': got_caps}))
    rows.append(check_row('runtime: the Docker runtime ran it (locked image, configured tag)',
                          c.get('Image') == (record.get('provisioning') or {}).get('image_id') and
                          (c.get('Config') or {}).get('Image') == cfg.get('conversation_image') and
                          (admitted.get('body') or {}).get('conversation_runtime') == 'docker',
                          {'image': c.get('Image'), 'config_image': (c.get('Config') or {}).get('Image'),
                           'body_runtime': (admitted.get('body') or {}).get('conversation_runtime')}))
    admitted_sha256 = dispatch_transport().body_sha256(admitted.get('body'))
    rows.append(check_row('the body sent is the admitted body', sent_sha256 == admitted_sha256,
                          'equal' if sent_sha256 == admitted_sha256 else
                          {'sent_sha256': sent_sha256, 'admitted_sha256': admitted_sha256}))
    problems, _ = container_problems(profile, record, report, c) if c else ([{'check': 'absent'}], [])
    rows.append(check_row('the container passes the declared shape (inspect rules)', not problems, problems))
    return all(r['ok'] for r in rows), rows


# ---------------------------------------------------------------- restart series (E-01.4.3)

RESTART_SERIES_COUNT = 500
RESTART_SERIES_RULE = (
    'Fixed before observation (plan leaf E-01.4.3). With the control: PASS only when at least '
    'the requested number of consecutive restarts ran and none had a main-process exit during '
    'start, none failed, and every start reached readiness. Recorded either way: every failed '
    "start, systemd's retry of it and the time to readiness, the distribution of start times, "
    "and each start's outcome line (a retried, slow or unverified start is never counted as "
    'clean).')
# the PyInstaller bootloader's line when the main process dies with an unhandled exception
START_EXIT_MARKERS = ('Failed to execute script',)
RETRY_SETTLE_S = 420          # a failed start's Restart=on-failure retry reaching active (ceiling)


def restart_row(index, detail):
    """One restart of the series (a drill server-restart result) for the record: its outcome
    line, the unit, whether the main process exited during the start, and the invocation's
    journal in full only when the start was not clean."""
    detail = detail or {}
    unit = detail.get('unit') or {}
    lines = (detail.get('invocation') or {}).get('lines') or []
    outcomes = [o for o in (ready_outcome(x) for x in lines) if o]
    outcome = outcomes[-1] if outcomes else None
    markers = [x for x in lines if any(m in str(x) for m in START_EXIT_MARKERS)]
    exit_during_start = bool(markers) or bool(outcome and outcome['start'] == 'main-exited')
    failed = detail.get('rc') != 0 or unit.get('ActiveState') != 'active' or \
        outcome is None or not outcome['ready']
    row = {'i': index, 'rc': detail.get('rc'), 'seconds': detail.get('seconds'),
           'outcome': outcome, 'exit_during_start': exit_during_start, 'failed': failed,
           'unit': {k: unit.get(k) for k in ('ActiveState', 'SubState', 'Result', 'NRestarts',
                                             'ExecMainStatus')}}
    if failed or exit_during_start or (outcome or {}).get('start') != 'clean':
        row['journal'] = lines
        row['stderr'] = detail.get('stderr')
    return row


def distribution(values):
    """n, min, p50, p90, p99, max (nearest rank) and 1-second buckets of a list of seconds."""
    data = sorted(v for v in values if isinstance(v, (int, float)))
    if not data:
        return {'n': 0}

    def rank(p):
        return data[max(0, min(len(data) - 1, int(-(-p * len(data) // 100)) - 1))]
    buckets = {}
    for v in data:
        key = f'{int(v)}-{int(v) + 1}'
        buckets[key] = buckets.get(key, 0) + 1
    return {'n': len(data), 'min': data[0], 'p50': rank(50), 'p90': rank(90), 'p99': rank(99),
            'max': data[-1], 'mean': round(sum(data) / len(data), 2),
            'buckets_s': dict(sorted(buckets.items(), key=lambda kv: int(kv[0].split('-')[0])))}


def settle_retry(observe, restarts_before, ceiling=RETRY_SETTLE_S, clock=time.monotonic,
                 sleep=time.sleep):
    """After a failed start: wait (polling the root helper's observe) until systemd's
    Restart=on-failure start is active, or the unit failed for good, under a ceiling. Returns
    the retried start's outcome, its unit and the seconds it took."""
    t0 = clock()
    obs = {}
    while True:
        obs = observe()
        unit = _unit(obs, DRILL_SERVER_UNIT)
        restarts = int(unit.get('NRestarts') or 0)
        if unit.get('ActiveState') == 'active' and restarts > restarts_before or \
                unit.get('ActiveState') == 'failed' or clock() - t0 >= ceiling:
            break
        sleep(1.0)
    lines = ((obs or {}).get('server_invocation') or {}).get('lines') or []
    outcomes = [o for o in (ready_outcome(x) for x in lines) if o]
    return {'seconds': round(clock() - t0, 1), 'outcome': outcomes[-1] if outcomes else None,
            'reached_readiness': unit.get('ActiveState') == 'active' and restarts > restarts_before
            and bool(outcomes) and outcomes[-1]['ready'],
            'unit': {k: unit.get(k) for k in ('ActiveState', 'SubState', 'Result', 'NRestarts')},
            'journal': lines}


def series_summary(rows, requested):
    """The series' counts, start-time distributions and verdict (RESTART_SERIES_RULE)."""
    first = [r for r in rows if r.get('i') is not None]
    classes = {}
    for r in first:
        key = (r.get('outcome') or {}).get('start') or 'no outcome line'
        classes[key] = classes.get(key, 0) + 1
    failed = [r['i'] for r in first if r['failed']]
    exits = [r['i'] for r in first if r['exit_during_start']]
    retried = [r for r in first if r.get('retry')]
    out = {'requested': requested, 'restarts': len(first),
           'main_process_exits_during_start': len(exits), 'exit_restarts': exits,
           'failed_starts': len(failed), 'failed_restarts': failed,
           'failed_starts_retried_to_readiness': sum(1 for r in retried
                                                     if r['retry'].get('reached_readiness')),
           'outcome_classes': classes,
           'ready_wait_seconds': distribution([(r.get('outcome') or {}).get('seconds')
                                               for r in first if (r.get('outcome') or {}).get('ready')]),
           'restart_seconds': distribution([r.get('seconds') for r in first if not r['failed']]),
           'failed_start_to_readiness_seconds': distribution(
               [(r.get('seconds') or 0) + r['retry']['seconds'] for r in retried
                if r['retry'].get('reached_readiness')]),
           'rule': RESTART_SERIES_RULE}
    out['verdict'] = 'PASS' if len(first) >= requested and not exits and not failed else 'FAIL'
    return out


def drill_restart_series(ctx, name, steps, chan, count=None):
    """E-01.4.3: ``count`` (default 500) consecutive restarts of the Agent Server through the
    root helper (systemctl restart), each with its outcome line; a failed start is followed to
    systemd's retry and its readiness. Then the reporting itself: a SIGKILLed server's
    Restart=on-failure start must say start=retried, and a manual restart after it is
    recorded."""
    count = RESTART_SERIES_COUNT if count is None else count
    if count < 1:
        raise Refused('REFUSED', '--limit must be at least 1')
    memo = {'rows': []}

    def observe():
        return _detail(chan()[2]('observe', {'journal_lines': 20}))

    def baseline():
        obs = observe()
        unit = _unit(obs, DRILL_SERVER_UNIT)
        procs = _server_processes(obs)
        memo['baseline'] = {'unit': {k: unit.get(k) for k in ('ActiveState', 'SubState',
                                                             'NRestarts', 'MainPID')},
                            'listening': _listening(obs), 'processes': len(procs)}
        return unit.get('ActiveState') == 'active' and _listening(obs), memo['baseline']

    def series():
        req = chan()[2]
        for i in range(1, count + 1):
            row = restart_row(i, _detail(req('server-restart')))
            if row['failed']:
                row['retry'] = settle_retry(observe, int(row['unit'].get('NRestarts') or 0))
            memo['rows'].append(row)
            if i % 50 == 0 or row['failed'] or row['exit_during_start']:
                log(f'restart-series: {i}/{count}; exits during start '
                    f'{sum(r["exit_during_start"] for r in memo["rows"])}, failed '
                    f'{sum(r["failed"] for r in memo["rows"])}')
        memo['summary'] = series_summary(memo['rows'], count)
        return memo['summary']['verdict'] == 'PASS', dict(memo['summary'], rows=memo['rows'])

    def retried_report():
        detail = _detail(chan()[2]('server-kill', {'ceiling': RETRY_SETTLE_S}))
        lines = (detail.get('invocation') or {}).get('lines') or []
        outcomes = [o for o in (ready_outcome(x) for x in lines) if o]
        outcome = outcomes[-1] if outcomes else None
        unit = detail.get('unit') or {}
        memo['retried_report'] = {'outcome': outcome, 'restarts_before': detail.get('restarts_before'),
                                  'unit': {k: unit.get(k) for k in ('ActiveState', 'SubState',
                                                                     'NRestarts')},
                                  'seconds': detail.get('seconds'), 'journal_tail': lines[-15:]}
        return bool(outcome and outcome['ready'] and
                    'retried' in outcome['start'].split(',')), memo['retried_report']

    def manual_after():
        row = restart_row(None, _detail(chan()[2]('server-restart')))
        memo['manual_after_retry'] = row
        return not row['failed'], row

    steps.run('the server is active and listening', baseline)
    steps.run(f'{count} consecutive restarts (systemctl restart)', series)
    steps.run('a Restart=on-failure start (SIGKILL) is reported start=retried', retried_report,
              always=True)
    steps.run('a manual restart after it (recorded)', manual_after, always=True)
    return memo


def drill(ctx, name, kind, canary_dir=None, raw=False, out_path=None, limit=None,
          ready_timeout=READY_TIMEOUT_S, channels=None, stop_fn=None, start_fn=None,
          admitted_fn=None):
    """drill (E-01.2.2 slice (b), TEST ONLY): on a running drill instance, ``fail-closed``
    (the key check and the guard), ``stored-state`` (every field of the job-writable stored
    state), ``root-scan`` (the guest-root P5 scan) or ``admitted-create`` (slice (a)'s admitted
    create sent live; ``admitted_fn(transport)`` runs the dispatch chain over the dispatch
    module's live transport, guest_transport.GuestTransport on the drill's GuestApi). One verdict,
    PASS or FAIL (root-scan may be UNKNOWN). ``channels(record) -> (api, facts, req)`` and the
    *_fn hooks stand in for the guest in tests."""
    if kind not in DRILL_KINDS:
        raise Refused('REFUSED', f'--kind must be one of {", ".join(DRILL_KINDS)}')
    idir, record = drill_instance(ctx, name)
    leaf = DRILL_KIND_LEAVES[kind]
    if drill_record_leaf(record) != leaf:
        raise Refused('REFUSED', f'{name} is a drill guest for {drill_record_leaf(record)}; '
                      f'--kind {kind} is a drill of {leaf} (create one with --drill-leaf {leaf})')
    out_file = None
    if out_path:
        out_file = Path(out_path).resolve()
        if os.path.lexists(out_file) or not out_file.parent.is_dir() or \
                inside(out_file, ctx.repo) or inside(out_file, idir):
            raise Refused('REFUSED', f'--out {out_path}: must be a new file in an existing '
                          'directory, outside the checkout and the instance directory')
    if kind == 'root-scan' and not canary_dir:
        raise Refused('REFUSED', 'root-scan needs --canaries (the set create planted)')
    canaries = load_canaries(canary_dir) if canary_dir else None
    profile = ctx.profile

    def default_channels(rec):
        ssh = Ssh(profile, idir, rec['ports']['ssh'])
        return GuestApi(ssh, profile), GuestFacts(ssh, profile), DrillChannel(ssh)
    channels = channels or default_channels
    stop_fn = stop_fn or (lambda: stop(ctx, name))
    start_fn = start_fn or (lambda: start(ctx, name, ready_timeout))
    current = {'record': record, 'channels': channels(record)}

    def chan():
        return current['channels']

    def reboot():
        stopped, started_ = stop_fn(), start_fn()
        _, current['record'] = running_instance(ctx, name)
        current['channels'] = channels(current['record'])
        if stopped.get('result') != 'stopped' or started_.get('result') != 'ready':
            raise Refused('REBOOT', f'stop {stopped.get("result")}, start {started_.get("result")}')
        return {'stop': {'result': stopped.get('result'), 'phases': stopped.get('phases')},
                'start': {'result': started_.get('result'), 'seconds': started_.get('seconds')}}

    t0, started = time.time(), utc_now()
    steps = DrillSteps(f'drill {kind}')
    memo = {}
    if kind == 'fail-closed':
        drill_fail_closed(ctx, name, steps, chan, reboot)
    elif kind == 'stored-state':
        memo = drill_stored_state(ctx, name, steps, chan, limit)
    elif kind == 'root-scan':
        memo = drill_root_scan(ctx, name, idir, steps, chan, canaries, raw)
    elif kind == 'f2-closed':
        memo = drill_f2_closed(ctx, name, steps, chan, reboot)
    elif kind == 'restart-series':
        memo = drill_restart_series(ctx, name, steps, chan, limit)
    else:
        if admitted_fn is None:
            raise Refused('REFUSED', 'admitted-create runs from integrations/dispatch/tests/'
                          'live_admitted_create.py (the dispatch chain builds the request)')

        def admitted_step():
            api, facts, _ = chan()
            transport = dispatch_transport().GuestTransport(api, profile, api_login=GUEST_API_LOGIN)
            try:
                admitted = admitted_fn(transport)
            except Exception as exc:  # a dispatch refusal or no answer: a failed step, then the cleanup
                raise Refused('CREATE', f'the dispatch chain stopped ({getattr(exc, "code", type(exc).__name__)}): '
                              f'{exc}', {'transport_calls': transport.calls}) from None
            report = facts()
            creates = [c for c in transport.calls if (c['method'], c['path']) == ('POST', '/api/conversations')]
            ok, rows = admitted_container_check(profile, current['record'], report, admitted,
                                                creates[0]['body_sha256'] if len(creates) == 1 else None)
            rows.insert(0, check_row('the dispatcher sent exactly one create, answered 2xx',
                                     len(creates) == 1 and _status_ok(creates[0]),
                                     [c.get('status') for c in creates]))
            memo['admitted'] = admitted
            return ok and rows[0]['ok'], {
                'admitted': admitted, 'transport_calls': transport.calls, 'checks': rows}

        def cleanup():
            api, _, _ = chan()
            cid = (memo.get('admitted') or {}).get('conversation_id')
            if not cid:
                return True, {'delete': 'nothing created'}
            deleted, = _call(api, {'method': 'DELETE', 'path': f'/api/conversations/{cid}',
                                   'timeout': 300})
            return deleted.get('status') == 200, {'delete': deleted.get('status')}
        steps.run('send_create of the admitted create; the container against it', admitted_step)
        steps.run('delete the admitted conversation', cleanup, always=True)
    result = 'PASS' if not steps.failed else 'FAIL'
    if kind == 'root-scan' and memo.get('verdict') == 'UNKNOWN':
        result = 'UNKNOWN'
    out = {'schema': DRILL_SCHEMA, 'operation': 'drill', 'kind': kind, 'plan_leaf': leaf,
           'labels': labels(profile),
           'profile': profile['name'], 'instance': name,
           'validation': {k: (record.get('validation') or {}).get(k) for k in ('mode', 'plan_leaf',
                                                                               'authority', 'script')},
           'started_at': started, 'ended_at': utc_now(), 'seconds': round(time.time() - t0, 1),
           'result': result, 'failed_steps': steps.failed, 'broken': steps.broken,
           'steps': steps.steps}
    out['record'] = write_record(idir, f'drill-{kind}', out)
    if out_file is not None:
        write_json_exclusive(out_file, json.loads(json.dumps(out, default=str)))
        out['out'] = str(out_file)
    return out


# ---------------------------------------------------------------- dispatcher custody (E-01.3.3)

CUSTODY_PROBE_SCHEMA = 'ai-engineering-harness/profiles/custody-probe-record/v1'
CUSTODY_CONVERSATION_ID = 'e0133b00-0000-4000-8000-00000000c0d1'
# Fixed before any run (plan leaf E-01.3.3; the Overseer's rulings F-1 to F-3 of 2026-11-11 and the Owner's
# correction of 2026-11-11 on the standing bot credential). Each step is PASS, FAIL or UNKNOWN; a lost or
# unreadable answer is UNKNOWN, never PASS.
CUSTODY_PROBE_RULE = (
    'PASS iff every step passes: (1) the key file and its directory have the owner, group and modes the profile '
    'declares (inspect); (2) the positive control: the key the dispatcher login reads in the guest has the '
    'fingerprint of the host copy and of the one the root step published (inspect); (3) zero hits of the outer '
    "key's fingerprints and of the builder's and reviewer's token fingerprints in the files and process "
    'environments of both conversation containers, which hold no credential file (job-access-probe, its '
    'credentials step and verdict); (4) a conversation runtime credential minted by the dispatcher answers 401 on '
    'every key-gated route of the outer server (HTTP 401, a WebSocket refused) and 2xx on its own conversation\'s '
    'inner server, which refuses a request without it; (5) one confirmed implement and one confirmed review '
    "attempt each get exactly the stage's mapped bot (Gitea's own view of the token) and their delivery records "
    'carry fingerprints only. FAIL when a step observes a violation; otherwise UNKNOWN when a step is UNKNOWN. '
    'STOP (FAIL, the run ends): a 2xx from the runtime credential on an outer route; a credential-provider write; '
    'a need to change the seed or the profile (the declared custody is not the bootstrap one); a new host port '
    '(the instance\'s forwarded ports change). Revocation and re-issue of a standing bot token are not part of '
    'this rule: they are the administrative lifecycle\'s (gitea_roles.py rotate), an optional separate step.')
# U-01.2 verifies the runtime-credentials route's response shape; until then the probe reads it under this
# assumption and a body of another shape makes step 4 UNKNOWN (never PASS).
ASSUMED_CREDENTIAL_SHAPE = ('POST /api/conversations/{id}/runtime/credentials (key-gated; routes.json dispatcher '
                            'not-used) answers 2xx with a JSON object whose "session_api_key" is the credential '
                            '(a string of 16 to 512 URL-safe characters): ASSUMED, to be checked live (U-01.2)')
RUNTIME_CREDENTIAL = re.compile(r'^[A-Za-z0-9_-]{16,512}$')

# Run as the dispatcher's guest login: the minted runtime credential (sealed: in this script's own text on
# standard input, never an argument) against every key-gated route of the outer server and against its own
# conversation's inner server; the outer key is never read. Prints statuses only; the credential is redacted
# from every answer and counted.
RUNTIME_CREDENTIAL_SWEEP = r'''import base64, http.client, json, os, socket, struct, sys
spec, cred = SEALED
spec = json.loads(base64.b64decode(spec).decode('utf-8'))
hits = 0
def text_of(raw):
    global hits
    text = raw.decode('utf-8', 'replace')
    hits += text.count(cred)
    return text.replace(cred, '<runtime credential redacted>')
def http_req(host, port, method, path, key):
    conn = http.client.HTTPConnection(host, port, timeout=60)
    try:
        conn.request(method, path, headers={'X-Session-API-Key': key} if key else {})
        resp = conn.getresponse()
        return {'status': resp.status, 'text': text_of(resp.read(1 << 14))[:120]}
    except OSError as exc:
        return {'error': type(exc).__name__}
    finally:
        conn.close()
def frame(op, payload):
    mask = os.urandom(4)
    return bytes([0x80 | op, 0x80 | len(payload)]) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
def ws(host, port, path):
    out = {}
    try:
        s = socket.create_connection((host, port), timeout=60)
    except OSError as exc:
        return {'error': type(exc).__name__}
    try:
        s.sendall(('GET ' + path + ' HTTP/1.1\r\nHost: ' + host + '\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                   'Sec-WebSocket-Key: ' + base64.b64encode(os.urandom(16)).decode() + '\r\n'
                   'Sec-WebSocket-Version: 13\r\n\r\n').encode())
        buf = b''
        while b'\r\n\r\n' not in buf:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
        head, _, data = buf.partition(b'\r\n\r\n')
        line = head.split(b'\r\n')[0].decode('latin-1').split()
        out['handshake'] = int(line[1]) if len(line) > 1 and line[1].isdigit() else None
        if out['handshake'] == 101:
            s.sendall(frame(1, json.dumps({'type': 'auth', 'session_api_key': cred}).encode()))
            while len(data) < 2:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
            if len(data) >= 2:
                n = data[1] & 0x7f
                while len(data) < 2 + n:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                out['opcode'] = data[0] & 0x0f
                if out['opcode'] == 8 and n >= 2:
                    out['close_code'] = struct.unpack('!H', data[2:4])[0]
    except OSError as exc:
        out['error'] = type(exc).__name__
    finally:
        s.close()
    return out
outer, inner = spec['outer'], spec['inner']
out = {'http': [], 'ws': []}
for method, path in spec['http']:
    out['http'].append({'method': method, 'path': path,
                        'with_credential': http_req(outer[0], outer[1], method, path, cred)})
for path in spec['ws']:
    out['ws'].append({'path': path, 'first_message_credential': ws(outer[0], outer[1], path)})
out['inner'] = {'with_credential': http_req(inner[0], inner[1], 'GET', inner[2], cred),
                'without': http_req(inner[0], inner[1], 'GET', inner[2], None)}
out['credential_occurrences'] = hits
print(json.dumps(out, sort_keys=True))
'''


def runtime_credential_of(body):
    """The credential in a runtime-credentials answer under ASSUMED_CREDENTIAL_SHAPE, or None."""
    value = body.get('session_api_key') if isinstance(body, dict) else None
    return value if isinstance(value, str) and RUNTIME_CREDENTIAL.match(value) else None


def inner_endpoint(profile, report, conversation_id):
    """(host, port) of the conversation's inner server as the guest sees it: the container's one published port on
    the declared host address (root facts), or None."""
    hex_id = conversation_id.replace('-', '')
    conv = conversations_config(provisioning_config(profile))
    published = conv.get('published') or {}
    mine = [c for c in report.get('containers') or [] if conversation_hex(c) == hex_id]
    if len(mine) != 1:
        return None
    bound = (((mine[0].get('NetworkSettings') or {}).get('Ports') or {}).get(published.get('container_port'))) or []
    ports = [b.get('HostPort') for b in bound if isinstance(b, dict) and b.get('HostIp') == published.get('host_ip')]
    if len(ports) != 1 or not str(ports[0]).isdigit():
        return None
    return published.get('host_ip'), int(ports[0])


def runtime_credential_spec(routes, outer, inner):
    """The sweep's requests: every key-gated HTTP route (admission session-key) and every WebSocket route of the
    pinned inventory at the outer listener, and its inner server's conversation count."""
    http = [(r['method'], concrete_path(r['path'])) for r in routes['routes']
            if r.get('admission') == 'session-key' and r['method'] != 'WEBSOCKET']
    ws = [concrete_path(r['path']) for r in routes['routes'] if r['method'] == 'WEBSOCKET']
    return {'outer': list(outer), 'inner': [inner[0], inner[1], '/api/conversations/count'], 'http': http, 'ws': ws}


def runtime_credential_verdict(sweep, spec):
    """Step 4: ('PASS' | 'FAIL' | 'UNKNOWN', detail, stop conditions). A 2xx on an outer route is a stop."""
    if not isinstance(sweep, dict) or sweep.get('credential_occurrences') is None:
        return 'UNKNOWN', {'reason': 'no sweep result'}, []
    stops, unanswered, admitted = [], [], []
    rows = {(r.get('method'), r.get('path')): (r.get('with_credential') or {}) for r in sweep.get('http') or []}
    for method, path in spec['http']:
        got = rows.get((method, path))
        status = (got or {}).get('status')
        if not isinstance(status, int):
            unanswered.append(f'{method} {path}')
        elif 200 <= status < 300:
            stops.append({'stop': 'the runtime credential got 2xx on an outer route', 'route': f'{method} {path}',
                          'status': status})
        elif status != 401:
            admitted.append({'route': f'{method} {path}', 'status': status})
    ws_rows = {r.get('path'): (r.get('first_message_credential') or {}) for r in sweep.get('ws') or []}
    for path in spec['ws']:
        got = ws_rows.get(path)
        if not got or ('handshake' not in got):
            unanswered.append(f'WEBSOCKET {path}')
        elif got.get('handshake') == 101 and got.get('close_code') != 4001:
            stops.append({'stop': 'the runtime credential was not refused on an outer WebSocket', 'route': path,
                          'observed': got})
    inner = sweep.get('inner') or {}
    with_cred = (inner.get('with_credential') or {}).get('status')
    without = (inner.get('without') or {}).get('status')
    detail = {'outer_http_routes': len(spec['http']), 'outer_ws_routes': len(spec['ws']),
              'outer_not_401': admitted, 'unanswered': unanswered, 'inner': {'with_credential': with_cred,
                                                                              'without': without},
              'credential_occurrences': sweep.get('credential_occurrences'), 'assumed': ASSUMED_CREDENTIAL_SHAPE}
    if stops or admitted or sweep.get('credential_occurrences') or \
            (isinstance(with_cred, int) and not 200 <= with_cred < 300) or \
            (isinstance(without, int) and 200 <= without < 300):
        return 'FAIL', detail, stops
    if unanswered or not isinstance(with_cred, int) or not isinstance(without, int):
        return 'UNKNOWN', detail, []
    return 'PASS', detail, []


def custody_key_verdict(profile, inspect_record):
    """Steps 1 and 2 from inspect's 'Agent Server secrets (custody)' check: the files' owner, group and modes as
    declared, the dispatcher login reads the key (READABLE), and the host copy's fingerprint equals the
    root-published one and the one read in the guest."""
    key = provisioning_config(profile)['agent_server']['session_key']
    checks = [c for p in (inspect_record or {}).get('properties') or [] for c in p.get('checks') or []
              if c.get('check') == 'Agent Server secrets (custody)']
    if len(checks) != 1 or not isinstance(checks[0].get('observed'), dict):
        unknown = {'reason': 'inspect gave no custody check'}
        return ('UNKNOWN', unknown), ('UNKNOWN', unknown)
    observed = checks[0]['observed']
    files = observed.get('files') if isinstance(observed.get('files'), dict) else {}
    key_dir = key['guest_path'].rsplit('/', 1)[0]
    want = {key['guest_path']: [key['owner'], key['group'], key['mode'], 'regular file'],
            key_dir: [key['guest_dir_owner'], key['guest_dir_group'], key['guest_dir_mode'], 'directory']}
    got = {p: files.get(p) for p in want}
    if any(v is None for v in got.values()):
        first = ('UNKNOWN', {'declared': want, 'observed': got})
    else:
        first = ('PASS' if got == want else 'FAIL', {'declared': want, 'observed': got})
    readable = (observed.get('agent_open') or {}).get(key['guest_path'])
    equal = (observed.get('host_copy') or {}).get('equal')
    detail = {'dispatcher_login_open': readable, 'host_copy': observed.get('host_copy'),
              'session_key_matches': observed.get('session_key_matches')}
    if readable is None or equal is None:
        second = ('UNKNOWN', detail)
    else:
        second = ('PASS' if readable == 'READABLE' and equal is True and observed.get('session_key_matches') is True
                  else 'FAIL', detail)
    return first, second


JOB_CREDENTIALS_STEP = 'credentials by name and fingerprint inside each job'


def custody_container_verdict(job_record, token_fingerprints):
    """Step 3 from job-access-probe's record: its verdict, and its credentials step searched the two outer key
    fingerprints and exactly the given bot token fingerprints, with no hit and no credential file in either
    container."""
    steps = [s for s in (job_record or {}).get('steps') or [] if s.get('step') == JOB_CREDENTIALS_STEP]
    if len(steps) != 1 or not isinstance(steps[0].get('detail'), dict) or 'ok' not in steps[0]:
        return 'UNKNOWN', {'reason': 'job-access-probe gave no credentials step'}
    detail = steps[0]['detail']
    searched = detail.get('searched') or {}
    containers = detail.get('containers') if isinstance(detail.get('containers'), dict) else {}
    hits = {cid: (c or {}).get('hits') for cid, c in containers.items() if (c or {}).get('hits')}
    files = {cid: (c or {}).get('credential_files') for cid, c in containers.items()
             if (c or {}).get('credential_files')}
    out = {'job_access_probe': (job_record or {}).get('result'), 'searched': searched, 'hits': hits,
           'credential_files': files, 'containers': len(containers)}
    complete = len(searched.get('outer (aieh v1)') or []) == 2 and \
        sorted(searched.get('gitea (sha256 prefix)') or []) == sorted(token_fingerprints) and len(containers) == 2
    if hits or files:
        return 'FAIL', out
    if not complete or steps[0].get('ok') is not True:
        return ('FAIL' if steps[0].get('ok') is False and complete else 'UNKNOWN'), out
    return ('PASS' if (job_record or {}).get('result') == 'PASS' else 'FAIL'), out


DELIVERY_KEYS = {'format', 'operationKey', 'attemptId', 'stage', 'role', 'bot', 'entry', 'credential', 'scopes',
                 'fingerprint'}
STAGE_BOTS = {'implement': ('builder', 'aieh-bot-builder'), 'review': ('reviewer', 'aieh-bot-reviewer')}


def attempt_deliveries_verdict(deliveries):
    """Step 5: one confirmed implement and one review attempt, each delivered exactly its stage's bot, the
    records fingerprint-only (the keys of role-token-delivery/v1, a sha256:<16 hex> fingerprint, no run of 40
    hex digits but the commit ids of the operation key)."""
    if not isinstance(deliveries, dict) or not isinstance(deliveries.get('records'), list):
        return 'UNKNOWN', {'reason': 'no delivery records'}
    records, problems = deliveries['records'], []
    by_stage = {}
    for r in records:
        if not isinstance(r, dict) or set(r) != DELIVERY_KEYS:
            problems.append('a record is not exactly role-token-delivery/v1')
            continue
        by_stage.setdefault(r['stage'], []).append(r)
        if (r['role'], r['bot']) != STAGE_BOTS.get(r['stage'], (None, None)):
            problems.append(f"{r['stage']} got {r['bot']}")
        if not GITEA_FINGERPRINT.match(str(r['fingerprint'])):
            problems.append(f"{r['stage']}: not a fingerprint")
        text = json.dumps({k: v for k, v in r.items() if k != 'operationKey'})
        if re.search(r'[0-9a-f]{40}', text):
            problems.append(f"{r['stage']}: a token-shaped value in the record")
    if sorted(by_stage) != ['implement', 'review'] or any(len(v) != 1 for v in by_stage.values()):
        problems.append(f'stages delivered: {sorted((s, len(v)) for s, v in by_stage.items())}')
    if deliveries.get('refused'):
        problems.append(f"refused: {deliveries['refused']}")
    return ('FAIL' if problems else 'PASS'), {'records': records, 'problems': problems}


def custody_verdict(steps, stop_conditions):
    """The run's verdict under CUSTODY_PROBE_RULE (and ACP_QUALIFICATION_RULE) from the steps' verdicts: FAIL on a
    stop or a FAIL, else UNKNOWN unless every step passed."""
    verdicts = [s.get('verdict') for s in steps]
    if stop_conditions or 'FAIL' in verdicts:
        return 'FAIL'
    if not steps or any(v != 'PASS' for v in verdicts):
        return 'UNKNOWN'
    return 'PASS'


def custody_probe(ctx, name, attempts_fn=None, out_path=None, channels=None, inspect_fn=None,
                  job_access_fn=None, ssh_fn=None):
    """custody-probe (plan leaf E-01.3.3; PREPARED, NOT RUN) on a running provisioned instance, under
    CUSTODY_PROBE_RULE, fixed before any run. ``attempts_fn(transport)`` runs the dispatch chain for one implement
    and one review attempt over the dispatch module's live transport and delivers each stage's token
    (integrations/dispatch/tests/live_custody_probe.py supplies it, with a credential provider that refuses every
    write); it returns {'records': [...], 'fingerprints': {role: fp}, 'refused': [...], 'provider_writes': n}. In
    order: (5) the attempts; (1, 2) inspect; (3) job-access-probe with the delivered tokens' fingerprints; (4) a
    disposable conversation, its runtime credential minted through the dispatcher's channel and swept in the
    guest, the conversation deleted; then the host-port check. ``channels(record) -> (api, facts)``, ``ssh_fn``,
    ``inspect_fn`` and ``job_access_fn`` stand in for the guest in tests."""
    if attempts_fn is None:
        raise Refused('REFUSED', 'custody-probe runs from integrations/dispatch/tests/live_custody_probe.py '
                      '(the dispatch chain dispatches and delivers the attempts)')
    idir = ctx.instance_dir(name)
    _, record = running_instance(ctx, name)
    if not record.get('provisioning'):
        raise Refused('REFUSED', f'{name} was not created with --provision; it runs no Agent Server')
    out_file = None
    if out_path:
        out_file = Path(out_path).resolve()
        if os.path.lexists(out_file) or not out_file.parent.is_dir() or \
                inside(out_file, ctx.repo) or inside(out_file, idir):
            raise Refused('REFUSED', f'--out {out_path}: must be a new file in an existing '
                          'directory, outside the checkout and the instance directory')
    profile = ctx.profile
    gt = dispatch_transport()
    ports_before = dict(record.get('ports') or {})
    steps, stop_conditions, memo = [], [], {}
    t0, started = time.time(), utc_now()
    try:
        gt.declared_custody(profile)
    except gt.TransportError as exc:
        stop_conditions.append({'stop': 'a change of the seed or the profile would be needed', 'detail': str(exc)})

    def default_channels(rec):
        ssh = Ssh(profile, idir, rec['ports']['ssh'])
        return GuestApi(ssh, profile), GuestFacts(ssh, profile)
    channels = channels or default_channels
    ssh = (ssh_fn or (lambda rec: Ssh(profile, idir, rec['ports']['ssh'])))(record)
    inspect_fn = inspect_fn or (lambda: inspect(ctx, name))
    job_access_fn = job_access_fn or (lambda fps: job_access_probe(ctx, name, token_fingerprints=[
        f'{role}={fp}' for role, fp in sorted(fps.items())]))
    api, facts = channels(record)
    caught = (Refused, OSError, ValueError, KeyError, TypeError, IndexError, subprocess.SubprocessError,
              gt.TransportError)

    def run(step, func):
        if stop_conditions:
            steps.append({'step': step, 'verdict': 'UNKNOWN', 'skipped': 'a stop condition'})
            return
        s = time.time()
        try:
            verdict, detail = func()
        except caught as exc:  # a lost answer is UNKNOWN, never PASS
            verdict, detail = 'UNKNOWN', {'error': getattr(exc, 'code', type(exc).__name__), 'message': str(exc)}
        steps.append({'step': step, 'verdict': verdict, 'seconds': round(time.time() - s, 1), 'detail': detail})
        log(f'custody-probe: {step}: {verdict}')

    def attempts_step():
        transport = gt.GuestTransport(api, profile, api_login=GUEST_API_LOGIN)
        deliveries = attempts_fn(transport)
        memo['fingerprints'] = dict((deliveries or {}).get('fingerprints') or {})
        if (deliveries or {}).get('provider_writes'):
            stop_conditions.append({'stop': 'a credential-provider write', 'count': deliveries['provider_writes']})
        verdict, detail = attempt_deliveries_verdict(deliveries)
        return verdict, dict(detail, transport_calls=transport.calls)

    def key_steps():
        record_ = inspect_fn()
        memo['key'] = custody_key_verdict(profile, record_)
        return memo['key'][0]

    def container_step():
        fps = memo.get('fingerprints') or {}
        if sorted(fps) != ['builder', 'reviewer']:
            return 'UNKNOWN', {'reason': 'the bot token fingerprints of step 5 are missing'}
        return custody_container_verdict(job_access_fn(fps), sorted(fps.values()))

    def credential_step():
        routes, problems = load_routes(ctx)
        body, _, _ = _fixture(ctx)
        server = provisioning_config(profile)['agent_server']['listener']
        created, = _call(api, {'method': 'POST', 'path': '/api/conversations', 'timeout': 600,
                               'json': dict(body, conversation_id=CUSTODY_CONVERSATION_ID)})
        memo['created'] = _status_ok(created)
        if not memo['created']:
            return 'UNKNOWN', {'create': created.get('status') or created.get('error')}
        minted, = _call(api, {'method': 'POST', 'timeout': 120,
                              'path': f'/api/conversations/{CUSTODY_CONVERSATION_ID}/runtime/credentials'})
        credential = runtime_credential_of(minted.get('body')) if _status_ok(minted) else None
        if credential is None:
            return 'UNKNOWN', {'mint': minted.get('status') or minted.get('error'), 'assumed': ASSUMED_CREDENTIAL_SHAPE}
        inner = inner_endpoint(profile, facts(), CUSTODY_CONVERSATION_ID)
        if inner is None or problems:
            return 'UNKNOWN', {'inner': inner, 'inventory_problems': problems}
        spec = runtime_credential_spec(routes, (server['address'], server['port']), inner)
        encoded = base64.b64encode(json.dumps(spec).encode('utf-8')).decode('ascii')
        result = ssh.run(['python3', '-'], input_text=f'SEALED = ({encoded!r}, {credential!r})\n'
                         + RUNTIME_CREDENTIAL_SWEEP, timeout=1800)
        try:
            sweep = json.loads(result.stdout.strip().splitlines()[-1])
        except (IndexError, ValueError):
            sweep = None
        memo['credential'] = credential
        del credential
        verdict, detail, stops = runtime_credential_verdict(sweep, spec)
        stop_conditions.extend(stops)
        return verdict, dict(detail, mint_status=minted.get('status'))

    def cleanup():
        if not memo.get('created'):
            return
        deleted, = _call(api, {'method': 'DELETE', 'path': f'/api/conversations/{CUSTODY_CONVERSATION_ID}',
                               'timeout': 300})
        memo['deleted'] = deleted.get('status')

    run('(5) one confirmed implement and one review attempt, each its mapped bot, fingerprints only', attempts_step)
    run('(1) key file custody as declared (inspect)', key_steps)
    second = memo.get('key', (None, ('UNKNOWN', {'reason': 'inspect did not answer'})))[1]
    steps.append({'step': '(2) positive control: the dispatcher login reads the key; its fingerprint equals the '
                  'host copy and the root-published one (inspect)', 'verdict': second[0], 'detail': second[1]})
    run('(3) no outer key or bot token fingerprint in either container (job-access-probe)', container_step)
    try:
        run('(4) the runtime credential: 401 on every key-gated outer route, 2xx only on its inner server',
            credential_step)
    finally:
        try:
            cleanup()
        except caught as exc:
            memo['deleted'] = getattr(exc, 'code', type(exc).__name__)
    _, after = running_instance(ctx, name)
    if dict(after.get('ports') or {}) != ports_before:
        stop_conditions.append({'stop': 'a new host port', 'before': ports_before, 'after': after.get('ports')})
    out = {'schema': CUSTODY_PROBE_SCHEMA, 'operation': 'custody-probe', 'plan_leaf': 'E-01.3.3',
           'labels': labels(profile), 'profile': profile['name'], 'instance': name, 'rule': CUSTODY_PROBE_RULE,
           'started_at': started, 'ended_at': utc_now(), 'seconds': round(time.time() - t0, 1),
           'result': custody_verdict(steps, stop_conditions), 'stop_conditions': stop_conditions,
           'conversation_deleted': memo.get('deleted'), 'steps': steps}
    if memo.get('credential') and memo['credential'] in json.dumps(out, default=str):
        raise Refused('SECRET', 'the custody-probe record would hold the runtime credential: not written')
    memo.pop('credential', None)
    out['record'] = write_record(idir, 'custody-probe', out)
    if out_file is not None:
        write_json_exclusive(out_file, json.loads(json.dumps(out, default=str)))
        out['out'] = str(out_file)
    return out


# ---------------------------------------------------------------- ACP qualification driver (S-03.3, slice 5)
#
# The live qualification of the first ACP coding provider (Claude Code) through the broker, PREPARED, NOT RUN
# (evidence/S-03.3-slice-plan.md, slice 5; the leaf's proof as amended on 2026-11-11, OA-19). On one disposable
# guest created with create --provision --inference, with the forward session held (A2, A3, A4) and one attempt
# token issued for the reserved conversation through the existing pipe
#   inference_control.py issue --conversation-id ACP_QUALIFICATION_CONVERSATION_ID ... | guest.py acp-qualification
# it admits and sends the pinned qualification create (integrations/dispatch/acp_qualification.py) through the
# dispatcher's transport (integrations/dispatch/guest_transport.py), sends one fixed prompt, observes the
# conversation container while the turn runs and after it (integrations/dispatch/conversation_containment.py),
# reads the conversation's events and the sets of containers and conversations, searches for the provider key,
# revokes the token at attempt end (decision 0015 section 3.3) and deletes the conversation. One record, under
# ACP_QUALIFICATION_RULE, fixed before any run.

ACP_QUALIFICATION_SCHEMA = 'ai-engineering-harness/profiles/acp-qualification-record/v1'
# reserved for the qualification create; the grant the token belongs to must be bound to it
ACP_QUALIFICATION_CONVERSATION_ID = 'a0333c00-0000-4000-8000-0000000ac0d1'
ACP_QUALIFICATION_FAMILY = 'anthropic-messages'     # the family whose auth the registry's ANTHROPIC_* names carry
ACP_QUALIFICATION_PROVIDER = 'claude-code'
# The fixed prompts, no repository content (A6). Whether the run asks for one delegated step is part of A6's
# presentation (the leaf's notes): the Owner's act names one of these, never another text.
ACP_QUALIFICATION_PROMPTS = {
    'single': 'Reply with exactly one word: ready',
    'delegated': 'Use exactly one sub-agent to answer this, then reply with exactly one word: ready',
}
ACP_KEY_MODES = ('off', 'synthetic', 'real')
ACP_SYNTHETIC_SOURCE = 'stdin-qualification'        # the qualification launcher's provider (S-03.2 slice 4)
ACP_REAL_KEY_ACT = re.compile(r'^[A-Za-z0-9][A-Za-z0-9 ._:()/-]{0,63}$')
ACP_REVOKER = 'tools/guest.py acp-qualification (the dispatcher\'s role during bootstrap)'
ACP_TURN_CEILING_S = 1800 + 120     # ACPAgentSettings.acp_prompt_timeout's default (1800 s) and a margin
ACP_TURN_END = ('finished', 'error', 'stuck', 'paused', 'waiting_for_confirmation')
ACP_EVENT_PAGES = 50
ACP_TOOL_CALL_KIND = 'ACPToolCallEvent'
ACP_NATIVE_CHILD_TOOL = 'start_child_conversation'
ACP_FORK_PATHS = ('/ask_agent', '/fork', '/children')
ACP_ASSUMED = {
    'message': 'POST /api/conversations/{id}/events with {"role": "user", "content": [{"type": "text", "text": '
               '<prompt>}], "run": true} sends the prompt and starts the turn; the outer server proxies it to the '
               'inner server (routes.json POST /api/conversations/{conversation_id}/{tail}, dispatcher value '
               '"validation")',
    'status': 'GET /api/conversations/{id} answers execution_status; a turn ends in one of ' + ', '.join(ACP_TURN_END),
    'events': 'GET /api/conversations/{id}/events/search?limit=100[&page_id=P] answers {items, next_page_id}; each '
              'item carries kind; an ACP tool call is kind ' + ACP_TOOL_CALL_KIND + ' (sdk/event/acp_tool_call.py) '
              'with a title; a native tool call carries tool_name',
    'inner': 'the inner server, inside the container at 127.0.0.1:8000 with the conversation\'s own key (read '
             'there from /proc/1/environ, as job-access-probe\'s route sweep does, never sent out), answers GET '
             '/api/conversations/search with items carrying id and parent_conversation_id',
    'agent': 'the create answer and GET /api/conversations/{id} carry agent with kind and acp_server',
}
ACP_HOST_VANTAGE_GAP = ('no guest-root channel: slice 1\'s collect host needs root (the PID namespace link and '
                        '/proc/<pid>/exe of the server user\'s processes), and a guest created with --inference has '
                        'none (no --drill helper; the root facts reporter runs a fixed script). Recorded UNKNOWN, '
                        'never PASS (finding F-6 of evidence/S-03.3-slice5-live-driver.md)')
# Fixed before any run (plan leaf S-03.3; the slice plan sections 4 and 5; the dispatch for slice 5). Each step is
# PASS, FAIL or UNKNOWN; a lost or unreadable answer is UNKNOWN, never PASS.
ACP_QUALIFICATION_RULE = (
    'PASS iff every step passes: (1) the opted-in guest holds the forward, the grant of the piped token is live, bound '
    'to the reserved conversation, of the family anthropic-messages, which is ready, with the named model in the '
    'grant and in the family\'s allowlist, the key-search mode matches the broker\'s provider key (synthetic: the '
    'launcher\'s, by fingerprint), and the outer server holds no conversation and no conversation container; (2) the '
    'pinned qualification create is admitted (acp_qualification.check_create) and created through the dispatcher\'s '
    'transport: 2xx, exactly one new container of the declared shape, the outer server listing exactly that '
    'conversation, the answer\'s acp_server claude-code when it names one; (3) the sets of containers and of outer '
    'and inner conversations read before the turn; (4) the fixed prompt accepted (2xx); (5) while the turn runs, the '
    'container view (every process a descendant of the inner server with the container\'s identity, no capability, '
    'no_new_privs, seccomp and cgroup, the claude-code adapter its direct child, no npx or npm, the admitted caps), '
    'its connections (none but to the inference endpoint, loopback or inbound to the inner server) and the guest-root '
    'view (the inspected caps, every member in the cgroup, no escape, the adapter seen with the same executable) all '
    'pass; an adapter missing only after the turn already ended is UNKNOWN; (6) the job contract in the qualification '
    'conversation (D-6): every process environment carries no credential-like name but the conversation keys and '
    'the attempt token\'s admitted name with a token-shaped value, no root, and that name observed; (7) the turn ends '
    'finished within the ceiling; (8) after the turn the container view, its connections and the guest-root view '
    'pass (the adapter no longer required) and the sets show no new container, no new outer conversation and every '
    'new inner conversation a child of this one; (9) the events are read in full and classify the delegation '
    'mechanisms (a) the provider\'s own processes and ACP tool calls, (b) an ACP session fork (never called by the '
    'driver), (c) the inner server\'s children route, (d) the native start_child_conversation tool, which must be '
    'absent; (10) the broker admitted at least one request of the grant (the base URL honoured); (11) the provider '
    'key search (mode synthetic or real) finds the key nowhere: inspect\'s P5 search of the guest and the instance '
    'files, and every Agent Server answer and container output of this run in memory, with valid positive controls '
    '(mode off: UNKNOWN); (12) the token revoked at attempt end; (13) the conversation deleted, its container gone '
    'and no outer conversation left. FAIL when a step observes a violation; otherwise UNKNOWN when a step is '
    'UNKNOWN. STOP (FAIL; the later steps are skipped, the key search, the revocation and the teardown still run): '
    'a process outside the container\'s lineage (an entered process, one outside the inner server\'s tree, an escaped '
    'child); an outer-server conversation that was not expected; an npx or npm process; a credential found in a '
    'recorded surface (the attempt token or the management key echoed in an Agent Server answer, a provider-key '
    'shaped value in a process environment, the provider key found by the search); a connection that reached any '
    'network destination other than the broker\'s inference endpoint.')

# Run inside the qualification conversation's container: the inner server's conversations (id and parent only),
# with the conversation's own key read from /proc/1/environ inside the container (never printed: its occurrences
# are counted and removed). argv[1] is the inner port.
ACP_INNER_CONVERSATIONS = r'''import http.client, json, sys, urllib.parse
port = int(sys.argv[1])
out = {'key_present': False, 'items': None, 'status': None, 'key_occurrences': 0, 'pages': 0}
key = ''
try:
    for e in open('/proc/1/environ', 'rb').read().split(bytes([0])):
        if e.startswith(b'OH_SESSION_API_KEYS_0='):
            key = e.split(b'=', 1)[1].decode('ascii')
except OSError as exc:
    out['error'] = type(exc).__name__
out['key_present'] = bool(key)
items, page = [], None
while key and out['pages'] < 20:
    path = '/api/conversations/search?limit=100' + ('&page_id=' + urllib.parse.quote(str(page)) if page else '')
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=30)
    try:
        conn.request('GET', path, headers={'X-Session-API-Key': key, 'Accept': 'application/json'})
        resp = conn.getresponse()
        text = resp.read(8 << 20).decode('utf-8', 'replace')
        out['status'] = resp.status
    except OSError as exc:
        out['error'] = type(exc).__name__
        break
    finally:
        conn.close()
    out['pages'] += 1
    out['key_occurrences'] += text.count(key)
    text = text.replace(key, '')
    try:
        body = json.loads(text)
    except ValueError:
        break
    if resp.status != 200 or not isinstance(body, dict) or not isinstance(body.get('items'), list):
        break
    items += [{'id': i.get('id'), 'parent_conversation_id': i.get('parent_conversation_id')}
              for i in body['items'] if isinstance(i, dict)]
    page = body.get('next_page_id')
    if not page:
        out['items'] = items
        break
print('AIEH-JOB-JSON ' + json.dumps(out, sort_keys=True))
'''


def _hex_id(value):
    """A conversation id as 32 lower-case hex digits (hyphens removed); a value that is not one is refused."""
    text = str(value or '').replace('-', '').lower()
    if not re.fullmatch(r'[0-9a-f]{32}', text):
        raise Refused('SETS', 'a conversation id that is not a UUID')
    return text


def no_host_vantage(record, state_pid):
    """The guest-root vantage of slice 1 on a guest created with --inference: there is no root channel."""
    raise Refused('HOST_VANTAGE', ACP_HOST_VANTAGE_GAP)


def read_real_provider_key(expected, provider_factory=None):
    """The real provider key for the key search (the slice plan's D-5), ONLY under the Owner's act that authorizes
    it: from the credential provider entry the broker reads ("AIEH model provider", the same account,
    credentials.select_provider), held in memory, never printed or written, and refused unless its fingerprint is
    ``expected`` (the running broker's provider key). ``provider_factory`` stands in for the provider in tests."""
    ic = inference_control()
    ks = key_search()
    factory = provider_factory or ic.broker.credentials.select_provider
    try:
        entry = factory().get(ic.broker.ENTRY)
    except Exception as exc:  # any provider failure: its type only, never what it read
        raise Refused('REAL_KEY', f'the credential provider did not answer ({type(exc).__name__})') from None
    if not isinstance(entry, (tuple, list)) or len(entry) != 2 or not isinstance(entry[1], str):
        raise Refused('REAL_KEY', 'the credential provider holds no provider key entry')
    key = entry[1]
    try:
        ks.check_fingerprint(key, expected)
    except ks.SearchError as exc:
        raise Refused('REAL_KEY', f'{exc.code}: the entry is not the running broker\'s provider key') from None
    return key


def acp_expected(profile, server_user, provider):
    """slice 1's expected values: the server user, the profile's job confinement and the admitted caps (the
    configuration's: the qualification create sends no container override)."""
    proc = jobs_config(profile).get('process') or {}
    cfg = (provisioning_config(profile)['agent_server'].get('config') or {}).get('content') or {}
    return {'uid': server_user.get('uid'), 'gid': server_user.get('gid'), 'capabilities': proc.get('capabilities'),
            'no_new_privs': proc.get('no_new_privs'), 'seccomp': proc.get('seccomp'),
            'limits': containment().expected_limits(cfg.get('conversation_container_memory'),
                                                    cfg.get('conversation_container_cpus'),
                                                    cfg.get('conversation_container_pids_limit')),
            'provider': provider}


def _failed_checks(verdict):
    return [c['check'] for c in (verdict or {}).get('checks') or [] if not c.get('ok')]


def acp_containment_stops(container_view, host_view, network_view):
    """The stop conditions a containment observation shows: a process outside the container's lineage (entered,
    outside the inner server's tree once the inner server is identified, an escaped child), an npx or npm process,
    a connection that reached another destination."""
    stops = []
    checks = {c['check'].split(':', 1)[0]: c for c in (container_view or {}).get('checks') or []}
    if not (checks.get('entered') or {}).get('ok', True):
        stops.append({'stop': 'a process outside the container\'s lineage (entered from outside)',
                      'observed': checks['entered'].get('observed')})
    ancestry = checks.get('ancestry') or {}
    if (checks.get('inner server') or {}).get('ok') and not ancestry.get('ok', True):
        stops.append({'stop': 'a process outside the container\'s lineage (not a descendant of the inner server)',
                      'observed': ancestry.get('observed')})
    if not (checks.get('npx') or {}).get('ok', True):
        stops.append({'stop': 'an npx or npm process', 'observed': checks['npx'].get('observed')})
    for c in (host_view or {}).get('checks') or []:
        if c['check'].startswith('no escape') and not c['ok']:
            stops.append({'stop': 'a process outside the container\'s lineage (an escaped child)',
                          'observed': c.get('observed')})
    if (network_view or {}).get('other_reached'):
        stops.append({'stop': 'a connection reached a destination other than the broker\'s inference endpoint',
                      'observed': network_view['other_reached']})
    return stops


def acp_delegation(events, provider_during, provider_after, children, transport_calls):
    """The four mechanisms of the slice plan section 2.4 as this run shows them, from the events, the provider's
    process trees, the inner server's new conversations and the driver's own calls."""
    tool_calls = [e for e in events if e.get('kind') == ACP_TOOL_CALL_KIND]
    native = [e.get('id') for e in events
              if e.get('tool_name') == ACP_NATIVE_CHILD_TOOL or
              (e.get('kind') == ACP_TOOL_CALL_KIND and ACP_NATIVE_CHILD_TOOL in str(e.get('title') or ''))]
    forks = [c for c in transport_calls if any(str(c.get('path', '')).endswith(p) or f'{p}?' in str(c.get('path'))
                                               for p in ACP_FORK_PATHS)]
    return {
        '(a) the provider\'s own tools and sub-agents': {
            'acp_tool_call_events': len(tool_calls),
            'tool_call_titles': [str(e.get('title'))[:120] for e in tool_calls][:50],
            'provider_processes': {'during': provider_during, 'after': provider_after},
            'observed': bool(tool_calls) or max(len(provider_during or []), len(provider_after or [])) > 2},
        '(b) an ACP session fork (ask_agent)': {
            'driver_called': [c.get('path') for c in forks],
            'observed': 'not separable: a fork runs inside the adapter process (slice plan section 2.4); the driver '
                        'never calls ask_agent, fork or children'},
        '(c) the inner server\'s children route': {'children': list(children), 'observed': bool(children)},
        '(d) OpenHands\' start_child_conversation tool': {'events_naming_it': native, 'observed': bool(native)},
    }


def acp_qualification_run(ctx, name, attempt_token, prompt, acp_model, key_mode='off', provider_key=None,
                          provider_key_fingerprint=None, real_key_act=None, out_path=None, channels=None,
                          broker=None, forward=None, inspect_fn=None, host_vantage=None, real_key_reader=None,
                          wait=None, turn_ceiling_s=ACP_TURN_CEILING_S):
    """acp-qualification (plan leaf S-03.3, slice 5; PREPARED, NOT RUN) under ACP_QUALIFICATION_RULE, fixed before
    any run. ``attempt_token`` comes from standard input (the inference_control.py issue pipe), never argv; records
    carry its fingerprint only. ``key_mode``: off (the default: the key search step is UNKNOWN), synthetic (S-03.2's
    synthetic key on standard input after the token, the launcher's, by ``provider_key_fingerprint``) or real (the
    provider key read through the credential provider only inside the key search step, and only with
    ``real_key_act`` naming the Owner's act that authorizes it). ``channels(record) -> (api, facts)``, ``broker``,
    ``forward``, ``inspect_fn(fingerprint, key)``, ``host_vantage(record, state_pid)``, ``real_key_reader(fp)`` and
    ``wait(fetch, done, ceiling)`` stand in for the guest, the broker and the clock in tests."""
    if prompt not in ACP_QUALIFICATION_PROMPTS:
        raise Refused('REFUSED', f'--prompt: one of {sorted(ACP_QUALIFICATION_PROMPTS)}')
    if key_mode not in ACP_KEY_MODES:
        raise Refused('REFUSED', f'--key-search: one of {list(ACP_KEY_MODES)}')
    if key_mode == 'synthetic' and (provider_key is None or not GITEA_FINGERPRINT.match(
            str(provider_key_fingerprint))):
        raise Refused('REFUSED', '--key-search synthetic needs the synthetic key on standard input and '
                      '--provider-key-fingerprint')
    if key_mode != 'synthetic' and provider_key is not None:
        raise Refused('REFUSED', 'a key on standard input is for --key-search synthetic only')
    if key_mode == 'real' and not ACP_REAL_KEY_ACT.match(str(real_key_act or '')):
        raise Refused('REFUSED', '--key-search real needs --real-key-act naming the Owner\'s act that authorizes '
                      'reading the provider key (off by default)')
    if key_mode != 'real' and real_key_act is not None:
        raise Refused('REFUSED', '--real-key-act is for --key-search real only')
    ic = inference_control()
    try:
        token_fp = ic.token_fingerprint(attempt_token)
    except ic.ControlError:
        raise Refused('REFUSED', 'the attempt token is not of the broker\'s shape') from None
    idir = ctx.instance_dir(name)
    _, record = running_instance(ctx, name)
    if not record.get('provisioning'):
        raise Refused('REFUSED', f'{name} was not created with --provision; it runs no Agent Server')
    if not inference_opted(record):
        raise Refused('REFUSED', f'{name} was not created with create --provision --inference: the provider has '
                      'no endpoint to reach')
    out_file = None
    if out_path:
        out_file = Path(out_path).resolve()
        if os.path.lexists(out_file) or not out_file.parent.is_dir() or \
                inside(out_file, ctx.repo) or inside(out_file, idir):
            raise Refused('REFUSED', f'--out {out_path}: must be a new file in an existing '
                          'directory, outside the checkout and the instance directory')
    profile = ctx.profile
    gt, cc = dispatch_transport(), containment()
    broker = broker or BrokerAccess()
    forward = forward or ForwardControl(ctx, name, broker)
    host_vantage = host_vantage or no_host_vantage
    real_key_reader = real_key_reader or read_real_provider_key
    wait = wait or wait_until
    inspect_fn = inspect_fn or (lambda fp, key: inspect(ctx, name, None, fp, key))
    cid, hex_id = ACP_QUALIFICATION_CONVERSATION_ID, ACP_QUALIFICATION_CONVERSATION_ID.replace('-', '')
    endpoint = inference_endpoint(profile)
    collector = (Path(ctx.repo) / 'integrations' / 'dispatch' / 'conversation_containment.py').read_text(
        encoding='utf-8')

    def default_channels(rec):
        ssh = Ssh(profile, idir, rec['ports']['ssh'])
        return GuestApi(ssh, profile), GuestFacts(ssh, profile)
    api, facts = (channels or default_channels)(record)
    steps, stop_conditions, memo = [], [], {'created': False, 'echoes': [], 'surfaces': []}
    t0, started = time.time(), utc_now()
    caught = (Refused, OSError, ValueError, KeyError, TypeError, IndexError, subprocess.SubprocessError,
              gt.TransportError, cc.ContainmentError)

    def sealed(requests, timeout=900):
        # every answer is scanned in the guest for the token (sealed) and kept in memory for the key search
        data = api(requests, timeout=timeout, secret=attempt_token)
        if isinstance(data, dict):
            count = data.get('sealed_occurrences')
            if count:
                memo['echoes'].append({'requests': [f"{r.get('method')} {r.get('path')}" for r in requests],
                                       'occurrences': count})
            memo['surfaces'].append(('agent server answer: ' + ' '.join(
                f"{r.get('method')} {str(r.get('path')).split('?')[0]}" for r in requests),
                json.dumps(data, sort_keys=True, default=str).encode('utf-8')))
        return data
    transport = gt.GuestTransport(sealed, profile, api_login=GUEST_API_LOGIN)

    def stop(what, **detail):
        stop_conditions.append(dict({'stop': what}, **detail))

    def call(method, path, body=None):
        before = len(memo['echoes'])
        try:
            answer = transport(method, path, body)
        except gt.TransportError as exc:
            if exc.code == 'SECRET_IN_ANSWER':
                stop('a credential found in a recorded surface (the management key in an Agent Server answer)',
                     route=f'{method} {path}')
            raise
        if len(memo['echoes']) > before:
            stop('a credential found in a recorded surface (the attempt token echoed in an Agent Server answer)',
                 route=f'{method} {path}', occurrences=memo['echoes'][-1]['occurrences'])
        return answer

    def body_of(answer):
        return answer.get('body') if isinstance(answer.get('body'), dict) else {}

    def ok_status(answer):
        return isinstance(answer.get('status'), int) and 200 <= answer['status'] < 300

    def in_container(command, timeout=300):
        answer = call('POST', f'/api/conversations/{cid}/bash/execute_bash_command',
                      {'command': command, 'cwd': '/workspace', 'timeout': timeout})
        body = body_of(answer)
        if not ok_status(answer) or body.get('exit_code') is None:
            raise Refused('CONTAINER', f'the command did not run in {cid} (HTTP {answer.get("status")})')
        stdout = body.get('stdout') or ''
        memo['surfaces'].append(('container output', stdout.encode('utf-8', 'surrogatepass')))
        return stdout

    def ours(report):
        return [c for c in report.get('containers') or [] if conversation_hex(c) == hex_id]

    def outer_ids():
        answer = call('GET', '/api/conversations/search?limit=100')
        body = body_of(answer)
        if not ok_status(answer) or not isinstance(body.get('items'), list) or body.get('next_page_id'):
            raise Refused('SETS', f'the outer server\'s conversation list was not read in one page '
                          f'(HTTP {answer.get("status")})')
        return sorted(_hex_id((i or {}).get('id')) for i in body['items'])

    def inner_rows():
        data = _job_json(in_container(container_python(ACP_INNER_CONVERSATIONS, str(cc.INNER_PORT)), 120))
        memo.setdefault('inner_reads', []).append({k: data.get(k) for k in (
            'key_present', 'status', 'pages', 'key_occurrences', 'error')})
        if not isinstance(data.get('items'), list):
            raise Refused('SETS', 'the inner server\'s conversations were not read')
        return [{'id': _hex_id(i.get('id')), 'parent_conversation_id':
                 None if i.get('parent_conversation_id') is None else _hex_id(i['parent_conversation_id'])}
                for i in data['items']]

    def sets_now(report):
        return {'containers': sorted(str(c.get('Id')) for c in report.get('containers') or []),
                'outer': outer_ids(), 'inner': inner_rows()}

    def observe(report, phase, provider):
        """slice 1's two vantages and the connections at one moment."""
        mine = ours(report)
        if len(mine) != 1:
            raise Refused('CONTAINER', f'{len(mine)} containers for the qualification conversation')
        expected = acp_expected(profile, report.get('server_user') or {}, provider)
        snap = cc.parse_output(in_container(container_python(collector, 'collect container'), 300))
        view = cc.container_verdict(snap, expected=expected)
        tree = cc.container_verdict(snap, expected=dict(expected, provider=ACP_QUALIFICATION_PROVIDER))
        net = cc.network_verdict(snap, endpoint=endpoint)
        state_pid = ((mine[0].get('State') or {}).get('Pid'))
        try:
            host_snap = host_vantage(record, state_pid)
            host = cc.host_verdict(host_snap, inspect=mine[0], container=snap, expected=expected)
            host_gap = None
        except Refused as exc:
            host, host_gap = None, str(exc)
        memo[f'provider_{phase}'] = [p.get('argv0') for p in tree.get('provider_tree') or []]
        detail = {'container': {k: view.get(k) for k in ('checks', 'inner_server', 'adapters', 'provider_tree',
                                                          'collector', 'outside_inner_server', 'process_count',
                                                          'vanished', 'listeners')},
                  'network': {k: net.get(k) for k in ('checks', 'connections', 'attempted', 'other_reached')},
                  'host': None if host is None else {k: host.get(k) for k in (
                      'checks', 'member_count', 'provider_seen', 'provider_vanished', 'appeared')},
                  'host_vantage': 'guest root' if host is not None else host_gap,
                  'container_guard_rejects': container_guard_rejects(report)}
        stops = acp_containment_stops(view, host, net)
        for s in stops:
            stop(s['stop'], phase=phase, observed=s['observed'])
        return view, host, net, detail, stops

    def run(step, func, always=False, needs=()):
        if not always and stop_conditions:
            steps.append({'step': step, 'verdict': 'UNKNOWN', 'skipped': 'a stop condition'})
            return
        missing = [n for n in needs if not memo.get(n)]
        if missing:
            steps.append({'step': step, 'verdict': 'UNKNOWN', 'skipped': f'not reached ({", ".join(missing)})'})
            return
        s = time.time()
        try:
            verdict, detail = func()
        except caught as exc:  # a lost answer is UNKNOWN, never PASS
            verdict, detail = 'UNKNOWN', {'error': getattr(exc, 'code', type(exc).__name__), 'message': str(exc)}
        steps.append({'step': step, 'verdict': verdict, 'seconds': round(time.time() - s, 1), 'detail': detail})
        log(f'acp-qualification: {step}: {verdict}')

    def preconditions():
        status, grant = broker.call('status'), broker.call('grant', token_fp)
        family = next((f for f in status.get('families') or []
                       if isinstance(f, dict) and f.get('id') == grant.get('family')), None) or {}
        key = status.get('provider_key') if isinstance(status.get('provider_key'), dict) else {}
        memo['family_models'] = list(family.get('models') or [])
        memo['provider_key_fingerprint'] = key.get('fingerprint')
        count = call('GET', '/api/conversations/count')
        report = facts()
        checks = {
            'the forward session is held': forward.status().get('held') is True,
            'the grant is live': grant.get('state') == 'live',
            'the grant is bound to the reserved conversation': grant.get('conversation_id') == cid,
            f'the grant\'s family is {ACP_QUALIFICATION_FAMILY}': grant.get('family') == ACP_QUALIFICATION_FAMILY,
            'the family is ready': family.get('ready') is True,
            'the model is in the grant and the family\'s allowlist':
                acp_model in (grant.get('models') or []) and acp_model in memo['family_models'],
            'the outer server holds no conversation': ok_status(count) and count.get('body') == 0,
            'no conversation container': report.get('containers') == [],
        }
        if key_mode == 'synthetic':
            checks['the broker holds the piped synthetic key'] = key.get('source') == ACP_SYNTHETIC_SOURCE and \
                key.get('fingerprint') == provider_key_fingerprint
        elif key_mode == 'real':
            checks['the broker holds a provider key from a credential provider'] = \
                bool(key.get('fingerprint')) and key.get('source') not in (None, ACP_SYNTHETIC_SOURCE)
        detail = {'checks': checks, 'token_fingerprint': token_fp,
                  'grant': {k: grant.get(k) for k in ('state', 'family', 'models', 'conversation_id', 'attempt_id',
                                                      'budget', 'expires_at')},
                  'family': {k: family.get(k) for k in ('id', 'status', 'ready', 'upstream', 'models', 'routes',
                                                        'query')},
                  'provider_key': {k: key.get(k) for k in ('fingerprint', 'source', 'provider')},
                  'key_search': key_mode, 'real_key_act': real_key_act}
        memo['ready'] = all(checks.values())
        return ('PASS' if memo['ready'] else 'FAIL'), detail

    def create_step():
        acp = acp_qualification()
        try:
            body = acp.build_create(conversation_id=cid, attempt_token=attempt_token, acp_model=acp_model,
                                    approved_models=memo['family_models'], profile=profile)
        except acp.QualificationRefused as exc:
            return 'FAIL', {'admission': exc.to_json()}
        answer = call('POST', '/api/conversations', body)
        detail = {'admission': 'admitted (acp_qualification.check_create)', 'status': answer.get('status'),
                  'sent_body_sha256': transport.calls[-1].get('body_sha256')}
        del body
        if not ok_status(answer):
            return 'FAIL', detail
        memo['created'] = True
        agent = body_of(answer).get('agent') if isinstance(body_of(answer).get('agent'), dict) else {}
        detail['agent'] = {k: agent.get(k) for k in ('kind', 'acp_server', 'acp_model')}
        report = facts()
        mine = ours(report)
        problems = container_problems(profile, record, report, mine[0])[0] if len(mine) == 1 else \
            [{'check': 'one container for the qualification conversation', 'observed': len(mine)}]
        outer = outer_ids()
        detail.update(containers=len(report.get('containers') or []), container_problems=problems, outer=outer)
        if outer != [hex_id]:
            stop('an outer-server conversation that was not expected', observed=outer)
        ok = len(report.get('containers') or []) == 1 and not problems and outer == [hex_id] and \
            agent.get('acp_server') in (None, ACP_QUALIFICATION_PROVIDER)
        return ('PASS' if ok else 'FAIL'), detail

    def before_step():
        report = facts()
        memo['before'] = sets_now(report)
        memo['rejects_before'] = container_guard_rejects(report)
        return 'PASS', {'sets': memo['before'], 'inner_reads': memo.get('inner_reads'),
                        'container_guard_rejects': memo['rejects_before']}

    def prompt_step():
        answer = call('POST', f'/api/conversations/{cid}/events',
                      {'role': 'user', 'content': [{'type': 'text', 'text': ACP_QUALIFICATION_PROMPTS[prompt]}],
                       'run': True})
        memo['sent'] = ok_status(answer)
        return ('PASS' if memo['sent'] else 'FAIL'), {'prompt': prompt, 'status': answer.get('status'),
                                                      'assumed': ACP_ASSUMED['message']}

    def execution_status():
        answer = call('GET', f'/api/conversations/{cid}')
        return answer, body_of(answer).get('execution_status')

    def during_step():
        report = facts()
        view, host, net, detail, stops = observe(report, 'during', ACP_QUALIFICATION_PROVIDER)
        _, status = execution_status()
        detail['execution_status_after_the_snapshot'] = status
        failed = _failed_checks(view) + _failed_checks(host) + _failed_checks(net)
        # the adapter checks of both views (the guest root's cross-view needs the adapter too)
        adapter_only = failed and all(c.startswith(('adapter', 'cross-view')) for c in failed)
        if stops or (failed and not (adapter_only and status in ACP_TURN_END)):
            return 'FAIL', detail
        if failed or host is None:
            return 'UNKNOWN', detail
        return 'PASS', detail

    def job_contract_step():
        names = attempt_token_environment(profile, record)
        report = facts()
        user = report.get('server_user') or {}
        jobs = jobs_config(profile)
        spec = {'pattern': (jobs.get('environment') or {}).get('credential_name_pattern'),
                'sockets': [str(p).replace('{uid}', str(user.get('uid'))) for p in jobs.get('engine_sockets') or []],
                'timeout': JOB_CONNECT_S}
        if names:
            spec['attempt_token'] = attempt_token_spec(names)
        arg = base64.b64encode(json.dumps(spec).encode('utf-8')).decode('ascii')
        data = _job_json(in_container(container_python(JOB_ENV_PROBE, arg), 300))
        ok, problems, root = job_env_verdict(profile, user, data, attempt_token_names=names)
        admission = attempt_token_admission(data, names)
        if admission['provider_key']:
            stop('a credential found in a recorded surface (a provider-key shaped value in a process environment)',
                 pids=sorted(admission['provider_key']))
        detail = {'admitted_names': list(names), 'admission': admission, 'problems': problems,
                  'root_obtainable': root,
                  'process_environments': {pid: e.get('names') for pid, e in
                                           (data.get('process_environments') or {}).items() if e.get('names')},
                  'terminal_names': data.get('terminal_names')}
        if not ok or root or admission['provider_key'] or not names:
            return 'FAIL', detail
        return ('PASS' if admission['admitted'] else 'UNKNOWN'), detail

    def turn_step():
        last, met = wait(lambda: execution_status()[1], lambda s: s in ACP_TURN_END, turn_ceiling_s)
        answer, status = execution_status()
        agent = body_of(answer).get('agent') if isinstance(body_of(answer).get('agent'), dict) else {}
        detail = {'execution_status': status, 'within_ceiling': met, 'ceiling_s': turn_ceiling_s,
                  'agent': {k: agent.get(k) for k in ('kind', 'acp_server', 'acp_model')},
                  'assumed': ACP_ASSUMED['status']}
        if not met:
            return 'UNKNOWN', detail
        return ('PASS' if status == 'finished' else 'FAIL'), detail

    def after_step():
        report = facts()
        view, host, net, detail, stops = observe(report, 'after', None)
        after = sets_now(report)
        sets = cc.sets_verdict(memo['before'], after, conversation_id=hex_id)
        memo['children'] = sets['delegation']['children_route']
        if sets['delegation']['outer_new']:
            stop('an outer-server conversation that was not expected', observed=sets['delegation']['outer_new'])
        detail.update(sets={'after': after, 'checks': sets['checks'], 'delegation': sets['delegation']},
                      container_guard_rejects={'before': memo.get('rejects_before'),
                                               'after': container_guard_rejects(report)})
        if stops or _failed_checks(view) or _failed_checks(host) or _failed_checks(net) or not sets['ok']:
            return 'FAIL', detail
        return ('UNKNOWN' if host is None else 'PASS'), detail

    def events_step():
        items, page, pages = [], None, 0
        while True:
            path = f'/api/conversations/{cid}/events/search?limit=100' + \
                (f'&page_id={urllib.parse.quote(str(page))}' if page else '')
            answer = call('GET', path)
            body = body_of(answer)
            if not ok_status(answer) or not isinstance(body.get('items'), list):
                return 'UNKNOWN', {'reason': f'an events page was not read (HTTP {answer.get("status")})',
                                   'pages': pages}
            items += [e for e in body['items'] if isinstance(e, dict)]
            pages += 1
            page = body.get('next_page_id')
            if not page:
                break
            if pages >= ACP_EVENT_PAGES:
                return 'UNKNOWN', {'reason': f'more than {ACP_EVENT_PAGES} pages of events', 'events': len(items)}
        final = call('GET', f'/api/conversations/{cid}/agent_final_response')
        text = json.dumps(final.get('body'), sort_keys=True, default=str)
        kinds = {}
        for e in items:
            kinds[str(e.get('kind'))] = kinds.get(str(e.get('kind')), 0) + 1
        mechanisms = acp_delegation(items, memo.get('provider_during'), memo.get('provider_after'),
                                    memo.get('children') or [], transport.calls)
        detail = {'events': len(items), 'pages': pages, 'kinds': kinds, 'mechanisms': mechanisms,
                  'agent_final_response': {'status': final.get('status'), 'bytes': len(text),
                                           'sha256': hashlib.sha256(text.encode('utf-8')).hexdigest()},
                  'assumed': ACP_ASSUMED['events']}
        if mechanisms['(d) OpenHands\' start_child_conversation tool']['observed'] or \
                mechanisms['(b) an ACP session fork (ask_agent)']['driver_called']:
            return 'FAIL', detail
        return ('PASS' if items else 'UNKNOWN'), detail

    def broker_step():
        grant = broker.call('grant', token_fp)
        detail = {k: grant.get(k) for k in ('state', 'requests', 'refused', 'usage', 'budget')}
        requests = grant.get('requests')
        if isinstance(requests, bool) or not isinstance(requests, int):
            return 'UNKNOWN', detail
        return ('PASS' if requests >= 1 else 'FAIL'), detail

    def key_step():
        if key_mode == 'off':
            return 'UNKNOWN', {'mode': 'off', 'reason': 'not run: the key search is off by default (--key-search '
                                                        'synthetic or, under its own Owner act, real)'}
        expected = memo.get('provider_key_fingerprint')
        if key_mode == 'synthetic':
            key = provider_key
        else:
            key = real_key_reader(expected)
            memo['real_key'] = key
        record_ = inspect_fn(expected, key)
        checks = [c for p in (record_ or {}).get('properties') or [] for c in p.get('checks') or []
                  if c.get('check') == INFERENCE_KEY_SEARCH_CHECK]
        inspected = checks[0].get('verdict') if len(checks) == 1 else None
        search = key_search().Search(key)
        for label, data in memo['surfaces']:
            search.capture(label, data)
        search.controls()
        report = search.report()
        del key
        detail = {'mode': key_mode, 'real_key_act': real_key_act, 'fingerprint': expected,
                  'inspect_p5': {'verdict': inspected,
                                 'observed': checks[0].get('observed') if len(checks) == 1 else None},
                  'this_run_in_memory': key_search_summary(report)}
        found = report['verdict'] == 'found' or inspected == 'FAIL'
        if found:
            stop('a credential found in a recorded surface (the provider key)')
            return 'FAIL', detail
        if inspected == 'PASS' and report['verdict'] == 'not-found':
            return 'PASS', detail
        return 'UNKNOWN', detail

    def revoke_step():
        grant = broker.call('grant', token_fp)
        if grant.get('state') == 'live':
            grant = broker.call('revoke', token_fp, 'attempt end', ACP_REVOKER)
        return ('PASS' if grant.get('state') == 'revoked' else 'FAIL'), {
            'token_fingerprint': token_fp, 'state': grant.get('state'), 'revocation': grant.get('revocation')}

    def teardown_step():
        answer = call('DELETE', f'/api/conversations/{cid}')
        report = facts()
        left = ours(report)
        count = call('GET', '/api/conversations/count')
        ok = ok_status(answer) and not left and ok_status(count) and count.get('body') == 0
        return ('PASS' if ok else 'FAIL'), {'delete': answer.get('status'), 'containers_left': len(left),
                                            'outer_count_after': count.get('body')}

    run('(1) preconditions: the opted-in guest, the forward, the grant, the family, nothing created yet',
        preconditions)
    run('(2) the qualification create, admitted and sent through the dispatcher\'s transport', create_step,
        needs=('ready',))
    try:
        run('(3) the sets before the turn: containers, outer and inner conversations', before_step,
            needs=('created',))
        run('(4) the fixed prompt sent', prompt_step, needs=('created', 'before'))
        run('(5) containment while the turn runs: the container view, its connections, the guest-root view',
            during_step, needs=('sent',))
        run('(6) the job contract in the qualification conversation (D-6)', job_contract_step, needs=('sent',))
        run('(7) the turn ends', turn_step, needs=('sent',))
        run('(8) containment after the turn, the network and the sets', after_step, needs=('sent', 'before'))
        run('(9) the conversation\'s events: the delegation mechanisms (a) to (d)', events_step, needs=('sent',))
        run('(10) the broker admitted the provider\'s requests under the token', broker_step, needs=('sent',))
        run(f'(11) the provider key searched for ({key_mode})', key_step, always=True, needs=('ready',))
    finally:
        run('(12) revoke the attempt token at attempt end (decision 0015 section 3.3)', revoke_step, always=True)
        run('(13) teardown: the conversation deleted, its container gone, no outer conversation left',
            teardown_step, always=True, needs=('created',))
    out = {'schema': ACP_QUALIFICATION_SCHEMA, 'operation': 'acp-qualification', 'plan_leaf': 'S-03.3',
           'labels': labels(profile), 'profile': profile['name'], 'instance': name, 'conversation': cid,
           'rule': ACP_QUALIFICATION_RULE, 'assumed': ACP_ASSUMED, 'prompt': {
               'name': prompt, 'text': ACP_QUALIFICATION_PROMPTS[prompt]}, 'acp_model': acp_model,
           'key_search': key_mode, 'started_at': started, 'ended_at': utc_now(), 'seconds': round(time.time() - t0, 1),
           'result': custody_verdict(steps, stop_conditions), 'stop_conditions': stop_conditions,
           'transport_calls': transport.calls, 'token_echoes': memo['echoes'], 'steps': steps}
    out = redact_secret(out, attempt_token, f'<attempt token {token_fp} redacted>')
    out['attempt_token'] = {'fingerprint': token_fp, 'redacted_from_record': out.pop('redactions')}
    for key in (provider_key, memo.pop('real_key', None)):
        if key is not None and key_search().Search(key).holds(json.dumps(out, sort_keys=True, default=str)):
            raise Refused('SECRET', 'the acp-qualification record would hold the provider key: not written')
    out['record'] = write_record(idir, 'acp-qualification', out)
    if out_file is not None:
        write_json_exclusive(out_file, json.loads(json.dumps(out, default=str)))
        out['out'] = str(out_file)
    return out


def defective_catalogue(catalogue, control_ids):
    """A copy of the catalogue whose named positive controls attempt a read that cannot succeed
    (proof item 1: an injected defective control), with the record of each replacement."""
    out = copy.deepcopy(catalogue)
    by_id = {c['id']: c for c in out.get('cases') or []}
    injected = []
    for cid in control_ids:
        case = by_id.get(cid)
        controls = {c.get('positive_control') for c in out.get('cases') or []}
        if case is None or case.get('kind') != 'permitted' or cid not in controls or \
                (case.get('probe') or {}).get('source') != 'containment-probe':
            raise Refused('REFUSED', f'--drill-defective-control {cid}: not a positive control run '
                          'by containment-probe itself')
        injected.append({'control': cid, 'original_probe': case['probe'],
                         'defective_probe': copy.deepcopy(DRILL_DEFECTIVE_PROBE),
                         'dependent_cases': sorted(c['id'] for c in out['cases']
                                                   if c.get('positive_control') == cid)})
        case['probe'] = copy.deepcopy(DRILL_DEFECTIVE_PROBE)
    return out, injected


# ---------------------------------------------------------------- host census (S-01.4)

HOST_CENSUS_SCHEMA = 'ai-engineering-harness/profiles/host-census-record/v1'
# The harness's host listeners: QEMU (SSH forward, QMP), the host-loopback Gitea (13300 and
# its egress-policy proxy; the pinned binary's process is named gitea-<version>-windows-amd64)
# and the Owner host's Vite dev and preview servers (strictPort).
HOST_CENSUS_PROCESSES = ('qemu-system-x86_64', 'gitea*')
HOST_CENSUS_PORTS = (13300, 5173, 4173)
HOST_CENSUS_LOOPBACK = '127.0.0.1'


def host_census_script(exclude_pids):
    """Read-only, unelevated: the TCP listeners and UDP endpoints of the named harness
    processes and of the harness ports, by PID (excluded PIDs are dropped before any process
    lookup), and the Windows Firewall profiles and rule count. Every failing cmdlet becomes a
    recorded error, never an elevation prompt."""
    ex = ','.join(str(int(p)) for p in exclude_pids) or '-1'
    names = ','.join(f"'{n}'" for n in HOST_CENSUS_PROCESSES)
    ports = ','.join(str(p) for p in HOST_CENSUS_PORTS)
    sel = ("Select-Object LocalAddress,LocalPort,OwningProcess,"
           "@{n='Process';e={$pn[[string]$_.OwningProcess]}}")
    return (
        "$ErrorActionPreference='SilentlyContinue';"
        f"$ex=@({ex});$pn=@{{}};"
        f"$named=@(Get-Process -Name {names} | Where-Object {{ $ex -notcontains $_.Id }});"
        "foreach($p in $named){$pn[[string]$p.Id]=$p.ProcessName};"
        "$t=@(foreach($p in $named){Get-NetTCPConnection -State Listen -OwningProcess $p.Id});"
        f"$q=@(Get-NetTCPConnection -State Listen -LocalPort {ports} | "
        "Where-Object { $ex -notcontains $_.OwningProcess });"
        "foreach($c in $q){$k=[string]$c.OwningProcess;if(-not $pn.ContainsKey($k)){"
        "$g=Get-Process -Id $c.OwningProcess;if($g){$pn[$k]=$g.ProcessName}else{$pn[$k]=''}}};"
        "$u=@(foreach($p in $named){Get-NetUDPEndpoint -OwningProcess $p.Id});"
        f"$t=@($t | {sel});$q=@($q | {sel});$u=@($u | {sel});"
        "$fw=$null;$fwe=$null;try{$fw=@(Get-NetFirewallProfile -ErrorAction Stop | "
        "Select-Object Name,@{n='Enabled';e={[string]$_.Enabled}},"
        "@{n='DefaultInboundAction';e={[string]$_.DefaultInboundAction}},"
        "@{n='DefaultOutboundAction';e={[string]$_.DefaultOutboundAction}})}"
        "catch{$fwe=$_.Exception.Message};"
        "$rc=$null;$rce=$null;try{$rc=@(Get-NetFirewallRule -ErrorAction Stop).Count}"
        "catch{$rce=$_.Exception.Message};"
        "ConvertTo-Json -Depth 4 -InputObject @{processes=@($named | Select-Object "
        "@{n='Id';e={$_.Id}},@{n='Name';e={$_.ProcessName}});tcp_by_process=$t;"
        "tcp_by_port=$q;udp_by_process=$u;firewall_profiles=$fw;firewall_profiles_error=$fwe;"
        "firewall_rule_count=$rc;firewall_rule_count_error=$rce}")


def host_census_verdict(data, exclude_pids=()):
    """(result, listeners, problems) of one census: every harness listener and UDP endpoint
    is on 127.0.0.1; an excluded PID never appears."""
    seen, listeners = set(), []
    for why, key in (('process', 'tcp_by_process'), ('port', 'tcp_by_port'),
                     ('process (udp)', 'udp_by_process')):
        for row in as_list(data.get(key)):
            ident = (key.startswith('udp'), row.get('LocalAddress'), row.get('LocalPort'),
                     row.get('OwningProcess'))
            if ident in seen:
                continue
            seen.add(ident)
            listeners.append({'protocol': 'udp' if key.startswith('udp') else 'tcp',
                              'address': row.get('LocalAddress'), 'port': row.get('LocalPort'),
                              'pid': row.get('OwningProcess'), 'process': row.get('Process'),
                              'found_by': why})
    problems = [dict(row, problem='not bound to 127.0.0.1') for row in listeners
                if row['address'] != HOST_CENSUS_LOOPBACK]
    problems += [dict(row, problem='an excluded PID was recorded') for row in listeners
                 if row['pid'] in set(exclude_pids)]
    if data.get('error'):
        problems.append({'problem': 'the census did not run', 'error': str(data['error'])[:300]})
    return ('PASS' if not problems else 'FAIL'), listeners, problems


def host_census(exclude_pids=(), out_path=None, repo=None):
    """host-census (S-01.4): a read-only, unelevated census of the harness's host listeners
    by PID (QEMU, Gitea, the Owner host's Vite servers), each of which must be on 127.0.0.1,
    and the Windows Firewall profiles and rule count, recorded as disclosure (UNKNOWN when a
    cmdlet is refused). It changes no rule and reads no file."""
    out_file = None
    if out_path:
        out_file = Path(out_path).resolve()
        if os.path.lexists(out_file) or not out_file.parent.is_dir() or \
                inside(out_file, repo or REPO):
            raise Refused('REFUSED', f'--out {out_path}: must be a new file in an existing '
                          'directory, outside the checkout')
    started = utc_now()
    data = powershell_json(host_census_script(exclude_pids))
    if not isinstance(data, dict):
        data = {'error': 'no JSON object'}
    result, listeners, problems = host_census_verdict(data, exclude_pids)
    profiles = as_list(data.get('firewall_profiles'))
    out = {'schema': HOST_CENSUS_SCHEMA, 'operation': 'host-census', 'started_at': started,
           'ended_at': utc_now(), 'excluded_pids': sorted(int(p) for p in exclude_pids),
           'processes': as_list(data.get('processes')), 'listeners': listeners,
           'problems': problems,
           'firewall': {
               'profiles': [{k: p.get(k) for k in ('Name', 'Enabled', 'DefaultInboundAction',
                                                   'DefaultOutboundAction')} for p in profiles]
               if profiles else f"UNKNOWN: {data.get('firewall_profiles_error') or 'no answer'}",
               'rule_count': data.get('firewall_rule_count')
               if isinstance(data.get('firewall_rule_count'), int)
               else f"UNKNOWN: {data.get('firewall_rule_count_error') or 'no answer'}",
               'disclosure': 'read only, unelevated; no rule is created or changed (S-01.4 '
                             'ruling R4)'},
           'result': result}
    if out_file is not None:
        write_json_exclusive(out_file, out)
        out['out'] = str(out_file)
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
    p = sub.add_parser('inference-forward-hold', help=argparse.SUPPRESS)
    p.add_argument('--spec', required=True)
    p = sub.add_parser('host-census', help='S-01.4: read-only, unelevated census of the '
                       "harness's host listeners by PID and the Windows Firewall disclosure")
    p.add_argument('--exclude-pid', action='append', type=int, default=[],
                   help='a process id the census must not look up or record (repeatable)')
    p.add_argument('--out', help='also write the record to this new file')
    for op in ('preflight', 'create', 'start', 'stop', 'destroy', 'recreate', 'inspect', 'exec',
               'exchange-push', 'exchange-pull', 'check-surfaces', 'netprobe', 'smoke',
               'provision-fetch', 'provision', 'conversation-smoke', 'admission-probe',
               'job-access-probe', 'containment-probe', 'drill', 'image-inspect',
               'inference-forward', 'acp-qualification'):
        p = sub.add_parser(op)
        p.add_argument('--profile', required=True, help='profile directory (never defaulted)')
        p.add_argument('--state-dir', required=True, help='the Owner-named state directory')
        if op not in ('preflight', 'provision-fetch', 'image-inspect'):
            p.add_argument('--name', required=True)
        if op == 'image-inspect':
            p.add_argument('--path', action='append',
                           help='an absolute path in the image, optionally #key#key to report '
                                'that field of a JSON file (repeatable; at least one --path or '
                                'text request)')
            p.add_argument('--list', action='append', metavar='GLOB',
                           help='text mode: the image paths a glob matches (* ? [..] within a '
                                'component, ** for any components), or EXE!MODULEGLOB: the PYZ '
                                'modules of a PyInstaller executable (repeatable)')
            p.add_argument('--excerpt', action='append', nargs=3, metavar=('PATH', 'START', 'END'),
                           help='text mode: lines START to END of a UTF-8 text file (repeatable)')
            p.add_argument('--search', action='append', nargs=2, metavar=('GLOB', 'REGEX'),
                           help='text mode: the matches of a regular expression (over bytes) in '
                                'the files, or EXE!MODULEGLOB modules, a glob names, each with '
                                '--context bytes around it (repeatable)')
            p.add_argument('--distinct', action='append', nargs=2, metavar=('GLOB', 'REGEX'),
                           help='text mode: the distinct values (the group, if the pattern has '
                                'one) a regular expression matches, with counts (repeatable)')
            p.add_argument('--strings', action='append', metavar='EXE!MODULEGLOB',
                           help='text mode: the string constants and names of each code object '
                                'of PYZ modules, walked as marshal data (repeatable)')
            p.add_argument('--context', type=int,
                           help=f'text mode: bytes before and after a match (default '
                                f'{IMAGE_TEXT_DEFAULT_CONTEXT}, at most {IMAGE_TEXT_MAX_CONTEXT})')
            p.add_argument('--max-matches', type=int,
                           help=f'text mode: matches reported per file and --search (default '
                                f'{IMAGE_TEXT_DEFAULT_MATCHES}, at most {IMAGE_TEXT_MAX_MATCHES})')
        if op in ('create', 'inspect', 'recreate', 'conversation-smoke'):
            p.add_argument('--canaries', help='a canary set written by the canaries operation')
        if op == 'inspect':
            p.add_argument('--provider-key-fingerprint',
                           help='decision 0015: sha256:<16 hex digits> of the model provider key '
                                '(its credential receipt); a P5 needle by fingerprint only')
            p.add_argument('--provider-key-stdin', action='store_true',
                           help='S-03.2: read the synthetic qualification key (the key of '
                                '--provider-key-fingerprint, the broker start receipt\'s) from '
                                'standard input, never argv, and search the P5 collection and its '
                                'host files for the key itself, raw and encoded, on the host')
        if op == 'conversation-smoke':
            p.add_argument('--restart', action='store_true',
                           help='also stop and start the guest, then reopen the conversation')
            p.add_argument('--openapi', help="the release's downloaded openapi.json: validate the "
                                             'fixture against it first (sha256 pinned)')
        if op in ('check-surfaces', 'smoke'):
            p.add_argument('--canaries', required=True,
                           help='a canary set written by the canaries operation')
        if op == 'smoke':
            p.add_argument('--durable', action='append', required=True,
                           help='a durable root to inventory before and after each destroy and '
                                'recreate (repeatable; stands for Owner data)')
            p.add_argument('--out', help='also write the smoke record to this new file')
        if op in ('conversation-smoke', 'admission-probe', 'job-access-probe', 'containment-probe',
                  'drill'):
            p.add_argument('--out', help='also write the record to this new file')
        if op == 'drill':
            p.add_argument('--kind', required=True, choices=DRILL_KINDS[:5],
                           help='E-01.2.2 slices (b) and (c) and E-01.4.3 (restart-series), TEST '
                                'ONLY, on a drill instance')
            p.add_argument('--canaries', help='root-scan: the canary set create planted')
            p.add_argument('--raw', action='store_true',
                           help='root-scan: also count occurrences on the raw block devices')
            p.add_argument('--limit', type=int, help='stored-state: only the first N alterations; '
                           f'restart-series: N restarts (default {RESTART_SERIES_COUNT})')
        if op == 'containment-probe':
            p.add_argument('--drill-defective-control', action='append', default=[],
                           help='E-01.2.2 slice (b), TEST ONLY, drill instances only: replace this '
                                'positive control with an attempt that cannot succeed (repeatable)')
            p.add_argument('--sensitivity', action='store_true',
                           help="S-02.1: also run the catalogue's live mutations, each of which "
                                'must be classified a success (FAIL)')
        if op in ('job-access-probe', 'containment-probe'):
            p.add_argument('--token-fingerprint', action='append', default=[],
                           help='LABEL=sha256:<16 hex digits>: a Gitea token fingerprint '
                                '(S-01.2.2 form) to search for inside the jobs (repeatable)')
        if op == 'job-access-probe':
            p.add_argument('--attempt-token-stdin', action='store_true',
                           help='decision 0015, an instance with the inference composition only: '
                                'read one attempt token (issued by the broker for the probe\'s '
                                'conversation) from standard input, never argv, and show it '
                                'forwarded, refused after revocation and refused without the '
                                'forward; records carry its fingerprint only')
            p.add_argument('--provider-key-stdin', action='store_true',
                           help='S-03.2, with --attempt-token-stdin: read the synthetic '
                                'qualification key from the next line of standard input and search '
                                'every answer the job received for the key itself, raw and encoded, '
                                'on the host; needs --provider-key-fingerprint')
            p.add_argument('--provider-key-fingerprint',
                           help="S-03.2: sha256:<16 hex digits>, the broker start receipt's "
                                'provider-key fingerprint; the key piped must be its key')
        if op == 'acp-qualification':
            p.add_argument('--attempt-token-stdin', action='store_true',
                           help='S-03.3 (required): read the attempt token, issued by inference_control.py issue '
                                'for the reserved conversation ' + ACP_QUALIFICATION_CONVERSATION_ID + ', from '
                                'standard input, never argv; records carry its fingerprint only')
            p.add_argument('--prompt', required=True, choices=sorted(ACP_QUALIFICATION_PROMPTS),
                           help='the fixed prompt the Owner\'s act A6 names (no repository content)')
            p.add_argument('--acp-model', required=True,
                           help="the create's acp_model: one model of the grant and of the family's allowlist")
            p.add_argument('--key-search', choices=ACP_KEY_MODES, default='off',
                           help='off (default); synthetic: the synthetic key on the next line of standard input '
                                '(needs --provider-key-fingerprint); real: the provider key through the '
                                'credential provider, only with --real-key-act')
            p.add_argument('--provider-key-fingerprint',
                           help="synthetic: sha256:<16 hex digits>, the broker start receipt's provider key")
            p.add_argument('--real-key-act',
                           help="real: the Owner's act that authorizes reading the provider key for the search")
            p.add_argument('--out', help='also write the record to this new file')
        if op == 'inference-forward':
            p.add_argument('--action', required=True, choices=FORWARD_ACTIONS,
                           help='decision 0015: start (idempotent), status or stop the SSH remote '
                                'forward of the instance\'s inference endpoint')
            p.add_argument('--broker-port', type=int,
                           help='start: must be components.inference_broker.inference_port (the '
                                'control port and any other are refused)')
        if op == 'exchange-push':
            p.add_argument('--repo', required=True, help='the repository to read the branch from')
            p.add_argument('--ref', required=True, help='one local branch')
            p.add_argument('--bundle-name', help='file name in the guest exchange directory')
        if op == 'exchange-pull':
            p.add_argument('--file', required=True, help='file name in the guest exchange directory')
        if op == 'create':
            p.add_argument('--egress-falsification', action='store_true',
                           help='S-01.4 fix-forward, with --provision: let job-access-probe add a '
                                "temporary default route via SLIRP's gateway (always removed) to "
                                'prove the egress guard with a route present')
        if op == 'create':
            p.add_argument('--drill', action='store_true',
                           help='E-01.2.2 slice (b), TEST ONLY, with --provision: seed the drill '
                                'helper (tools/guest_drill.py) as a second user-data part')
            p.add_argument('--drill-leaf', choices=DRILL_LEAVES,
                           help='with --drill (required): the plan leaf whose drills the guest '
                                'is for, recorded in its launch record')
            p.add_argument('--inference', action='store_true',
                           help='decision 0015, with --provision: apply the opt-in inference '
                                'composition (sshd remote-forward directives, the container '
                                "guard's one ACCEPT, daemon.json bip and dns); the Owner's "
                                'guest hardening act, off by default')
        if op in ('create', 'recreate', 'smoke'):
            p.add_argument('--provision', action='store_true',
                           help='F-04.1: seed the provisioning manifest of the verified host '
                                'stage (smoke: and run provision after create and recreate)')
        if op in ('create', 'start', 'recreate', 'netprobe', 'smoke', 'conversation-smoke', 'drill'):
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
        if op == 'inference-forward-hold':
            return forward_hold(args.spec)
        if op == 'host-census':
            result = host_census(args.exclude_pid, args.out)
            print(json.dumps(result, indent=2, sort_keys=True, default=str))
            return 0 if result.get('result') == 'PASS' else 1
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
        elif op == 'image-inspect':
            excerpts = []
            for path, start, end in args.excerpt or ():
                if not (start.isdigit() and end.isdigit()):
                    raise Refused('REFUSED', f'--excerpt {path!r} {start} {end}: line numbers')
                excerpts.append((path, int(start), int(end)))
            text = parse_image_text_requests(args.list, excerpts, args.search, args.distinct,
                                             args.strings, args.context, args.max_matches)
            if not text['requests'] and (args.context is not None or args.max_matches is not None):
                raise Refused('REFUSED', '--context and --max-matches need a text request')
            result = image_inspect(ctx, args.path or [], text) if text['requests'] else \
                image_inspect(ctx, args.path or [])
        elif op == 'create':
            if args.egress_falsification and not args.provision:
                raise Refused('REFUSED', '--egress-falsification needs --provision')
            if args.drill and not args.provision:
                raise Refused('REFUSED', '--drill needs --provision')
            if args.drill_leaf and not args.drill:
                raise Refused('REFUSED', '--drill-leaf needs --drill')
            if args.inference and (not args.provision or args.drill):
                raise Refused('REFUSED', '--inference needs --provision and is never a drill')
            result = create(ctx, args.name, args.ready_timeout, canaries, provision=True,
                            egress_falsification=args.egress_falsification, drill=args.drill,
                            drill_leaf=args.drill_leaf, inference=args.inference) \
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
        elif op == 'conversation-smoke':
            result = conversation_smoke(ctx, args.name, args.canaries, args.restart, args.openapi,
                                        args.out, args.ready_timeout)
        elif op == 'admission-probe':
            result = admission_probe(ctx, args.name, args.out)
        elif op == 'job-access-probe':
            token = read_attempt_token(sys.stdin) if args.attempt_token_stdin else None
            key = read_provider_key(sys.stdin, args.provider_key_fingerprint) \
                if args.provider_key_stdin else None
            result = job_access_probe(ctx, args.name, args.out, args.token_fingerprint,
                                      attempt_token=token, provider_key=key)
        elif op == 'inference-forward':
            result = inference_forward(ctx, args.name, args.action, args.broker_port)
        elif op == 'acp-qualification':
            if not args.attempt_token_stdin:
                raise Refused('REFUSED', 'acp-qualification needs --attempt-token-stdin (the token from the '
                              'inference_control.py issue pipe)')
            token = read_attempt_token(sys.stdin)
            key = read_provider_key(sys.stdin, args.provider_key_fingerprint) \
                if args.key_search == 'synthetic' else None
            result = acp_qualification_run(ctx, args.name, token, args.prompt, args.acp_model, args.key_search,
                                           provider_key=key, provider_key_fingerprint=args.provider_key_fingerprint,
                                           real_key_act=args.real_key_act, out_path=args.out)
        elif op == 'containment-probe':
            result = containment_probe(ctx, args.name, args.out, args.token_fingerprint,
                                       args.sensitivity,
                                       defective_controls=args.drill_defective_control)
        elif op == 'drill':
            result = drill(ctx, args.name, args.kind, args.canaries, args.raw, args.out,
                           args.limit, args.ready_timeout)
        else:
            key = read_provider_key(sys.stdin, args.provider_key_fingerprint) \
                if args.provider_key_stdin else None
            result = inspect(ctx, args.name, canaries, args.provider_key_fingerprint, key)
    except Refused as exc:
        print(f'REFUSED {exc.code}: {exc}', file=sys.stderr)
        print(json.dumps({'result': 'refused', 'code': exc.code, 'message': str(exc),
                          'detail': exc.detail}, indent=2, sort_keys=True, default=str))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    if result.get('operation') in ('check-surfaces', 'netprobe', 'smoke', 'conversation-smoke',
                                   'admission-probe', 'job-access-probe', 'containment-probe',
                                   'drill', 'acp-qualification'):
        return 0 if result.get('result') == 'PASS' else 1
    failed = result.get('result') in ('unavailable', 'not-ready') or \
        'FAIL' in (result.get('verdicts') or {}).values() or \
        (result.get('compatibility') or {}).get('verdict') == 'FAIL' or \
        result.get('create', {}).get('result') == 'not-ready'
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
