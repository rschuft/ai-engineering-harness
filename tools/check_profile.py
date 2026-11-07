"""Schema check for execution-profile declarations (plan leaf F-03.2.1).

Checks each ``profiles/<name>/profile.json`` against the execution-profile contract
(``profiles/README.md``, ``profiles/properties.json``) without running any provider:

- every boot input (profiles P9) is pinned by digest, and every committed file a
  profile pins still has that digest;
- a provision lock (``provider.provision_lock``, F-04.1a) still has its pinned digest
  and pins every artifact by an https URL, a size and a sha256, the Debian ones at one
  snapshot timestamp and the image as index, platform manifest and config digest;
- the tier, provider and nesting labels are present and valid (profiles P11);
- no host share is declared or configured (profiles P3, P4);
- the guest's approved volume and mount table (``guest_storage``) and the exchange
  bounds (``exchange``) are declared, and for QEMU the volume table matches
  ``launch.argv`` exactly (profiles P3, P4; F-03.3.1);
- every forward and management endpoint binds to 127.0.0.1 (profiles P7); a declared
  enforcement point names its status, and a qualified or failed one cites its
  evidence and, when qualified, a reachability table of permitted and denied paths;
  an endpoint that is still deferred has no port and no guest forwarding rule
  (F-03.3.2);
- ceilings are declared and match the provider configuration (profiles P2);
- exactly one accelerator and no TCG fallback (contract section 4);
- the lifecycle is the contract's closed set (contract section 3).

A boot input that cannot be known without the provider (for example firmware
shipped by an Incus server) may be declared with ``"pin_status": "unknown"`` and an
``unpinned_reason``. Such inputs are reported as UNRESOLVED; ``--strict`` fails on
them. Anything else unpinned is a FAIL.

Usage (from the repository root):
    python -I -B tools/check_profile.py [--strict] [PROFILE ...]

PROFILE is a profile directory or its profile.json; the default is every
profiles/*/profile.json. Exit status 0 when every profile passes, 1 otherwise.
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCHEMA = 'ai-engineering-harness/profiles/profile/v1'
HEX64 = re.compile(r'^[0-9a-f]{64}$')
HEX128 = re.compile(r'^[0-9a-f]{128}$')
DIGEST = re.compile(r'^sha256:[0-9a-f]{64}$')
PROVISION_LOCK_SCHEMA = 'ai-engineering-harness/profiles/provision-lock/v1'
SNAPSHOT_ARCHIVE = 'https://snapshot.debian.org/archive/'
SNAPSHOT_TIMESTAMP = re.compile(r'^\d{8}T\d{6}Z$')
LOOPBACK = '127.0.0.1'
REQUIRED_INPUTS = ('image', 'firmware', 'kernel', 'seed', 'provider_binary', 'profile_revision')
# QEMU options a profile may use. Anything else (-virtfs, -fsdev, -drive, -usb, -audio,
# -vnc, -qmp, -monitor, the deprecated -mon, -kernel, a second -accel through -machine
# ...) is refused, so a share, device or interface cannot enter through an option this
# check does not parse.
QEMU_FLAGS = {'-no-user-config', '-nodefaults'}
QEMU_VALUE_OPTIONS = {'-name', '-machine', '-accel', '-cpu', '-smp', '-m', '-L', '-bios',
                      '-blockdev', '-device', '-netdev', '-display', '-chardev', '-serial',
                      '-object', '-pidfile', '-rtc', '-boot', '-msg'}
# -object types a profile may create: only the QMP monitor (QEMU 11.1 replaces
# '-mon mode=control' with '-object monitor-qmp'). Its properties as the pinned binary
# lists them ('-object monitor-qmp,help': chardev, close-action, pretty) plus the
# required id. Other objects (memory backends with share=on, monitor-hmp, secrets,
# filters ...) are refused.
QEMU_OBJECTS = {'monitor-qmp': {'id', 'chardev', 'close-action', 'pretty'}}
QEMU_DEVICES = {'virtio-blk-pci', 'virtio-net-pci', 'virtio-rng-pci'}
QEMU_BLOCK_DRIVERS = {'file', 'qcow2', 'raw'}
INCUS_ISO_SOURCES = {'cloud-init:config', 'agent:config'}
INCUS_DEVICE_TYPES = {'disk', 'nic', 'proxy'}
OWNER_PROFILE_PREFIXES = ('c:\\users', 'c:/users', '%userprofile%', '~', '$home', '/home/',
                          '/users/', '/root')


class Report:
    def __init__(self, name):
        self.name = name
        self.errors = []
        self.unresolved = []

    def fail(self, message):
        self.errors.append(message)

    def unknown(self, message):
        self.unresolved.append(message)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def load_flow_yaml(path):
    """Read a YAML file written in JSON-compatible flow style (comment lines first)."""
    lines = Path(path).read_text(encoding='utf-8').splitlines()
    body = '\n'.join(line for line in lines if not line.lstrip().startswith('#'))
    return json.loads(body)


def check_repo_file(report, root, label, entry):
    """A committed file pinned by sha256 must exist and still have that digest."""
    if not isinstance(entry, dict) or not entry.get('path') or not entry.get('sha256'):
        report.fail(f'{label}: needs path and sha256')
        return
    if not HEX64.match(str(entry['sha256'])):
        report.fail(f'{label}: sha256 is not 64 lowercase hex digits')
        return
    path = root / entry['path']
    if not path.is_file():
        report.fail(f'{label}: pinned file {entry["path"]} is missing')
    elif sha256_file(path) != entry['sha256']:
        report.fail(f'{label}: {entry["path"]} does not match its pinned sha256')


def check_pin(report, label, entry, *, version_ok=False):
    """An input is pinned by sha256, or explicitly declared unknown with a reason."""
    digest = entry.get('sha256')
    if isinstance(digest, str) and HEX64.match(digest):
        return
    if digest is not None:
        report.fail(f'{label}: sha256 is not 64 lowercase hex digits')
        return
    if entry.get('pin_status') == 'unknown' and entry.get('unpinned_reason'):
        if version_ok and not entry.get('version'):
            report.fail(f'{label}: an unknown digest needs an exact version pin')
            return
        report.unknown(f'{label}: {entry["unpinned_reason"]}')
        return
    report.fail(f'{label}: not pinned by digest (no sha256 and no declared unknown pin)')


def check_labels(report, profile, properties):
    labels = profile.get('labels')
    if not isinstance(labels, dict):
        report.fail('labels: missing (profiles P11 needs tier, provider and nesting)')
        return
    allowed = properties['artifact_labels']
    for key in ('tier', 'provider', 'nesting'):
        if not labels.get(key):
            report.fail(f'labels: missing {key} (profiles P11)')
    tier = labels.get('tier')
    if tier and tier not in allowed['tier']:
        report.fail(f'labels: tier {tier!r} is not one of {allowed["tier"]}')
    if labels.get('nesting') and labels['nesting'] not in allowed['nesting']:
        report.fail(f'labels: nesting {labels["nesting"]!r} is not one of {allowed["nesting"]}')
    if tier and not str(profile.get('name', '')).startswith(f'{tier}-'):
        report.fail(f'name: {profile.get("name")!r} does not carry the tier prefix {tier}- '
                    '(contract section 4)')


def check_status(report, profile):
    status = profile.get('status') or {}
    if status.get('operational') is not False and not status.get('operational_evidence'):
        report.fail('status: operational must be false until C6 evidence is recorded')


def check_accelerator(report, profile):
    accel = profile.get('accelerator') or {}
    if not accel.get('name'):
        report.fail('accelerator: name missing')
    if accel.get('fallback') != 'none':
        report.fail(f'accelerator: fallback must be "none", found {accel.get("fallback")!r} '
                    '(no TCG fallback; contract section 4)')
    if accel.get('on_unavailable') != 'TIER_UNAVAILABLE':
        report.fail('accelerator: on_unavailable must be TIER_UNAVAILABLE')


def check_boot_inputs(report, profile, root):
    inputs = profile.get('boot_inputs')
    if not isinstance(inputs, dict):
        report.fail('boot_inputs: missing (profiles P9)')
        return
    for key in REQUIRED_INPUTS:
        if key not in inputs:
            report.fail(f'boot_inputs: {key} missing (profiles P9)')
    image = inputs.get('image') or {}
    if 'image' in inputs:
        if not str(image.get('url', '')).startswith('https://'):
            report.fail('boot_inputs.image: needs an https url')
        if not (isinstance(image.get('sha256'), str) and HEX64.match(image['sha256'])):
            report.fail('boot_inputs.image: not pinned by sha256 (profiles P9)')
        if image.get('sha512') is not None and not HEX128.match(str(image['sha512'])):
            report.fail('boot_inputs.image: sha512 is not 128 lowercase hex digits')
        if image.get('backing_file') is not None:
            report.fail('boot_inputs.image: a backing file is an unpinned boot input')
        meta = image.get('metadata')
        if meta is not None:
            check_repo_file(report, root, 'boot_inputs.image.metadata', meta)
        if isinstance(image.get('incus_fingerprint'), dict):
            check_pin(report, 'boot_inputs.image.incus_fingerprint', image['incus_fingerprint'])
    if 'firmware' in inputs:
        check_pin(report, 'boot_inputs.firmware', inputs['firmware'] or {})
    kernel = inputs.get('kernel')
    if 'kernel' in inputs:
        if not isinstance(kernel, dict) or 'used' not in kernel:
            report.fail('boot_inputs.kernel: declare used: true or false')
        elif kernel['used']:
            for part in ('kernel', 'initrd'):
                check_pin(report, f'boot_inputs.kernel.{part}', kernel.get(part) or {})
    seed = inputs.get('seed')
    if 'seed' in inputs:
        templates = (seed or {}).get('templates')
        if not isinstance(templates, dict) or not templates:
            report.fail('boot_inputs.seed: templates missing')
        else:
            for name, entry in templates.items():
                check_repo_file(report, root, f'boot_inputs.seed.templates.{name}', entry)
        if (seed or {}).get('per_instance') and not seed.get('record_at_create'):
            report.fail('boot_inputs.seed: a per-instance seed must be recorded at create')
    binary = inputs.get('provider_binary')
    if 'provider_binary' in inputs:
        binary = binary or {}
        if not binary.get('ref'):
            report.fail('boot_inputs.provider_binary: ref missing')
        version = binary.get('version') or (profile.get('provider') or {}).get('version')
        if not version:
            report.fail('boot_inputs.provider_binary: exact version missing')
        check_pin(report, 'boot_inputs.provider_binary', dict(binary, version=version),
                  version_ok=True)
        ref = str(binary.get('ref', ''))
        name = ref.split('.', 2)[2] if ref.startswith('provider.binaries.') else None
        target = ((profile.get('provider') or {}).get('binaries') or {}).get(name)
        if target is None:
            report.fail(f'boot_inputs.provider_binary: ref {ref!r} names no provider binary')
        elif target.get('sha256') != binary.get('sha256'):
            report.fail('boot_inputs.provider_binary: sha256 differs from the provider binary pin')
    revision = inputs.get('profile_revision')
    if 'profile_revision' in inputs and (revision or {}).get('kind') != 'git-revision':
        report.fail('boot_inputs.profile_revision: kind must be git-revision')


def check_provider(report, profile, root):
    provider = profile.get('provider')
    if not isinstance(provider, dict) or not provider.get('name') or not provider.get('version'):
        report.fail('provider: name and exact version required (contract section 10)')
        return
    for name, entry in (provider.get('binaries') or {}).items():
        check_pin(report, f'provider.binaries.{name}', dict(entry, version=provider['version']),
                  version_ok=True)
    if provider.get('artifact_lock') is not None:
        check_repo_file(report, root, 'provider.artifact_lock', provider['artifact_lock'])
    if provider.get('provision_lock') is not None:
        check_provision_lock(report, profile, root, provider['provision_lock'])
    for name, entry in (profile.get('provider_files') or {}).items():
        check_repo_file(report, root, f'provider_files.{name}', entry)


def provision_lock_problems(lock, profile_name):
    """Static shape of a provision lock (F-04.1a): every artifact pinned by an https URL,
    a size and a sha256; one snapshot timestamp for the Debian indexes and packages; the
    image chained index -> platform manifest -> config digest (the image ID) with its
    layers; the crane tool pinned with its archive and its crane.exe member."""
    problems = []

    def pinned(label, entry, url_prefix='https://'):
        if not isinstance(entry, dict):
            problems.append(f'{label}: missing')
            return
        url = entry.get('url')
        if not isinstance(url, str) or not url.startswith(url_prefix):
            problems.append(f'{label}: url must start with {url_prefix}')
        size = entry.get('size')
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            problems.append(f'{label}: size is not a byte count')
        if not HEX64.match(str(entry.get('sha256', ''))):
            problems.append(f'{label}: sha256 is not 64 lowercase hex digits')

    if lock.get('schema') != PROVISION_LOCK_SCHEMA:
        problems.append(f'schema: expected {PROVISION_LOCK_SCHEMA}')
    if lock.get('profile') != profile_name:
        problems.append(f'profile: {lock.get("profile")!r} is not {profile_name!r}')
    debian = lock.get('debian') or {}
    stamp = str((debian.get('snapshot') or {}).get('timestamp', ''))
    if not SNAPSHOT_TIMESTAMP.match(stamp):
        problems.append('debian.snapshot.timestamp: not a snapshot.debian.org timestamp')
    suites = debian.get('suites') or []
    if not suites:
        problems.append('debian.suites: none')
    for suite in suites:
        base = f'{SNAPSHOT_ARCHIVE}{suite.get("archive")}/{stamp}/'
        if suite.get('base_url') != base:
            problems.append(f'debian.suites.{suite.get("suite")}: base_url is not {base}')
        for entry in suite.get('files') or []:
            pinned(f'debian.suites.{suite.get("suite")}.{entry.get("path")}', entry, base)
            if isinstance(entry.get('url'), str) and entry['url'] != base + str(entry.get('path')):
                problems.append(f'debian.suites.{suite.get("suite")}.{entry.get("path")}: url '
                                'is not base_url + path')
    packages = debian.get('packages') or []
    if not packages:
        problems.append('debian.packages: none')
    for package in packages:
        pinned(f'debian.packages.{package.get("name")}', package,
               f'{SNAPSHOT_ARCHIVE}debian/{stamp}/pool/')
        if not str(package.get('filename', '')).endswith('.deb') or not package.get('version'):
            problems.append(f'debian.packages.{package.get("name")}: needs a .deb filename and '
                            'a version')
    image = lock.get('image') or {}
    for key in ('index_digest', 'manifest_digest', 'config_digest'):
        if not DIGEST.match(str(image.get(key, ''))):
            problems.append(f'image.{key}: not a sha256 digest')
    if image.get('ref') != f'{image.get("repository")}@{image.get("index_digest")}':
        problems.append('image.ref: must be repository@index_digest')
    if image.get('image_id') != image.get('config_digest'):
        problems.append('image.image_id: must equal config_digest')
    layers = image.get('layers')
    if not isinstance(layers, list) or not layers or not all(
            isinstance(l, dict) and DIGEST.match(str(l.get('digest', ''))) and
            isinstance(l.get('size'), int) for l in layers):
        problems.append('image.layers: must list sha256 digests and sizes')
    pinned('release_binary', lock.get('release_binary'))
    crane = (lock.get('tools') or {}).get('crane')
    pinned('tools.crane', crane)
    if isinstance(crane, dict):
        member = crane.get('member') or {}
        if member.get('name') != 'crane.exe' or not HEX64.match(str(member.get('sha256', ''))):
            problems.append('tools.crane.member: needs crane.exe with a sha256')
        if not (crane.get('checksums_source') or {}).get('url'):
            problems.append('tools.crane.checksums_source: missing')
    return problems


def check_provision_lock(report, profile, root, entry):
    """The provision lock is pinned by sha256 like any committed file, then shape-checked."""
    before = len(report.errors)
    check_repo_file(report, root, 'provider.provision_lock', entry)
    if len(report.errors) != before:
        return
    try:
        lock = json.loads((root / entry['path']).read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        report.fail(f'provider.provision_lock: cannot read ({exc})')
        return
    for problem in provision_lock_problems(lock, profile.get('name')):
        report.fail(f'provider.provision_lock: {problem}')


def check_ceilings(report, profile):
    ceilings = profile.get('ceilings')
    if not isinstance(ceilings, dict):
        report.fail('ceilings: missing (profiles P2)')
        return {}
    for key in ('vcpu', 'memory_mib', 'root_disk_gib', 'scratch_disk_gib'):
        value = ceilings.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            report.fail(f'ceilings: {key} must be a positive integer (profiles P2)')
    return ceilings


def owner_profile_path(path):
    lowered = path.strip().lower()
    return lowered.startswith(OWNER_PROFILE_PREFIXES) or '%userprofile%' in lowered


def check_state_dir(report, profile):
    state = profile.get('state_dir')
    if not isinstance(state, dict):
        report.fail('state_dir: missing (contract section 11)')
        return
    if state.get('default') is not None:
        report.fail('state_dir: must not be defaulted; the Owner names it (contract section 11)')
    proposed = state.get('proposed')
    if proposed is not None:
        if owner_profile_path(proposed):
            report.fail(f'state_dir: {proposed!r} is inside the Owner\'s profile')
        if ',' in proposed:
            report.fail('state_dir: a comma breaks QEMU option syntax')


def check_lifecycle(report, profile, properties):
    lifecycle = profile.get('lifecycle')
    if not isinstance(lifecycle, dict):
        report.fail('lifecycle: missing (contract section 3)')
        return
    expected = properties['lifecycle']['operations']
    if sorted(lifecycle.get('operations') or []) != sorted(expected):
        report.fail(f'lifecycle: operations must be exactly {expected}')
    if not set(lifecycle.get('modes') or []) <= set(properties['lifecycle']['modes']):
        report.fail('lifecycle: unknown mode')
    timeout = lifecycle.get('stop_timeout_s')
    if not isinstance(timeout, int) or isinstance(timeout, bool) or not 0 < timeout <= 300:
        report.fail('lifecycle: stop_timeout_s must be an integer from 1 to 300')
    missing = [op for op in expected if op not in (lifecycle.get('bindings') or {})]
    if missing:
        report.fail(f'lifecycle: no provider binding for {missing}')


def check_network(report, profile, properties, root=REPO):
    network = profile.get('network')
    if not isinstance(network, dict):
        report.fail('network: missing (profiles P7)')
        return
    if network.get('ipv6') is not False:
        report.fail('network: ipv6 must be false unless listed (profiles P7)')
    if not network.get('enforcement_point'):
        report.fail('network: enforcement_point must be named (profiles P7)')
    classes = set()
    for endpoint in network.get('endpoints') or []:
        cls = endpoint.get('class')
        classes.add(cls)
        if cls not in properties['endpoint_classes']:
            report.fail(f'network: unknown endpoint class {cls!r}')
        bind = endpoint.get('host_bind')
        if isinstance(bind, str) and re.match(r'^[0-9.:\[\]a-fA-F]+$', bind) and bind != LOOPBACK:
            report.fail(f'network: {cls} endpoint binds to {bind}, not {LOOPBACK}')
    missing = set(properties['endpoint_classes']) - classes
    if missing:
        report.fail(f'network: endpoint classes not enumerated: {sorted(missing)}')
    check_enforcement_point(report, profile, root)


ENFORCEMENT_STATUSES = ('candidate', 'qualified', 'failed')
EVIDENCE_PATH = re.compile(r'^evidence/[A-Za-z0-9._-]+\.md$')
REACHABILITY_FIELDS = ('path', 'protocol', 'observed')


def guestfwd_rules(argv):
    rules = []
    for i, arg in enumerate(argv or []):
        if arg == '-netdev' and i + 1 < len(argv):
            rules += [part for part in str(argv[i + 1]).split(',') if part.startswith('guestfwd=')]
    return rules


def check_enforcement_point(report, profile, root):
    """profiles P7 (F-03.3.2): the enforcement point's status and its evidence."""
    network = profile.get('network') or {}
    point = network.get('enforcement_point')
    deferred = [e for e in network.get('endpoints') or []
                if str(e.get('status', '')).startswith('deferred')]
    for endpoint in deferred:
        if endpoint.get('host_port') is not None:
            report.fail(f'network: deferred {endpoint.get("class")} endpoint declares a host port')
    active_guestfwd = [e for e in network.get('endpoints') or [] if e not in deferred
                       and 'guestfwd' in str(e.get('mechanism', ''))]
    rules = guestfwd_rules((profile.get('launch') or {}).get('argv'))
    if len(rules) != len(active_guestfwd):
        report.fail(f'launch.argv: {len(rules)} guestfwd rule(s), but {len(active_guestfwd)} '
                    'active guestfwd endpoint(s) are declared (profiles P7)')
    if isinstance(point, str):
        return                                   # a candidate, named in prose
    if not isinstance(point, dict):
        report.fail('network: enforcement_point must be a string or an object')
        return
    if not isinstance(point.get('mechanism'), str) or not point['mechanism'].strip():
        report.fail('network: enforcement_point.mechanism must be named')
    status = point.get('status')
    if status not in ENFORCEMENT_STATUSES:
        report.fail(f'network: enforcement_point.status must be one of {list(ENFORCEMENT_STATUSES)}')
        return
    if status == 'candidate':
        return
    evidence = point.get('evidence')
    if not isinstance(evidence, str) or not EVIDENCE_PATH.match(evidence):
        report.fail(f'network: a {status} enforcement point cites its evidence (evidence/<file>.md)')
    elif not (root / evidence).is_file():
        report.fail(f'network: enforcement_point.evidence {evidence} is missing')
    if not point.get('qualified_by'):
        report.fail(f'network: a {status} enforcement point names the leaf that tested it '
                    '(qualified_by)')
    if 'validation_overlay' in point:
        check_repo_file(report, root, 'network.enforcement_point.validation_overlay',
                        point['validation_overlay'])
    if status != 'qualified':
        return
    table = network.get('reachability')
    if not isinstance(table, dict):
        report.fail('network: a qualified enforcement point needs a reachability table')
        return
    for kind in ('permitted', 'denied'):
        rows = table.get(kind)
        if not isinstance(rows, list) or not rows:
            report.fail(f'network: reachability.{kind} must list at least one path')
            continue
        for n, row in enumerate(rows):
            if not isinstance(row, dict) or any(not isinstance(row.get(f), str) or
                                                not row[f].strip() for f in REACHABILITY_FIELDS):
                report.fail(f'network: reachability.{kind}[{n}] needs {list(REACHABILITY_FIELDS)}')


def check_isolation(report, profile):
    if profile.get('host_shares') != []:
        report.fail('host_shares: must be an empty list (profiles P3, P4)')
    if not isinstance(profile.get('nested_virt_exposed'), bool):
        report.fail('nested_virt_exposed: must be declared true or false (profiles P12)')


# --- guest storage and exchange (profiles P3, P4; F-03.3.1) ----------------

STORAGE_ROLES = {'root', 'scratch', 'configuration-medium'}
# The share types the contract's P3 inspection names; forbidden_fstypes must cover them.
CONTRACT_SHARE_FSTYPES = {'9p', 'virtiofs', 'drvfs', 'fuse.sshfs', 'cifs', 'nfs', 'smb3'}
DIRECTORY_ROLES = ('exchange', 'scratch')
STORAGE_FILE = re.compile(r'^(\{instance_dir\}/[A-Za-z0-9._-]+|\{input:[a-z_]+\})$')


def block_specs(device):
    """The format node and, for an overlay, its backing node, of one declared device."""
    return [spec for spec in (device, device.get('backing')) if isinstance(spec, dict)]


def check_guest_storage(report, profile):
    """guest_storage: the approved volume and mount table that inspect compares with."""
    storage = profile.get('guest_storage')
    provider = (profile.get('provider') or {}).get('name')
    if storage is None:
        if provider == 'qemu':
            report.fail('guest_storage: missing (profiles P3, P4 compare the guest with a '
                        'declared volume and mount table)')
        return
    if not isinstance(storage, dict):
        report.fail('guest_storage: must be an object')
        return
    devices = storage.get('block_devices')
    if not isinstance(devices, dict) or not devices:
        report.fail('guest_storage.block_devices: missing')
        devices = {}
    roles = [d.get('role') for d in devices.values() if isinstance(d, dict)]
    for role in ('root', 'scratch'):
        if roles.count(role) != 1:
            report.fail(f'guest_storage.block_devices: exactly one {role} device required')
    serials = []
    for key, dev in devices.items():
        label = f'guest_storage.block_devices.{key}'
        if not isinstance(dev, dict):
            report.fail(f'{label}: must be an object')
            continue
        if dev.get('role') not in STORAGE_ROLES:
            report.fail(f'{label}: role {dev.get("role")!r} is not one of {sorted(STORAGE_ROLES)}')
        if not isinstance(dev.get('serial'), str) or not dev.get('serial'):
            report.fail(f'{label}: serial missing')
        serials.append(dev.get('serial'))
        if not isinstance(dev.get('read_only'), bool):
            report.fail(f'{label}: read_only must be true or false')
        if dev.get('role') == 'configuration-medium' and (dev.get('read_only') is not True or
                                                          dev.get('mounted') is not False):
            report.fail(f'{label}: a configuration medium must be read-only and not mounted '
                        '(profiles P4)')
        if dev.get('role') in ('root', 'scratch') and dev.get('read_only') is not False:
            report.fail(f'{label}: the {dev.get("role")} disk is writable')
        backing = dev.get('backing')
        if backing is not None and (not isinstance(backing, dict) or
                                    backing.get('read_only') is not True):
            report.fail(f'{label}.backing: a backing image must be read-only')
        for spec in block_specs(dev):
            for field in ('node', 'file_node'):
                if not isinstance(spec.get(field), str) or not spec.get(field):
                    report.fail(f'{label}: {field} missing')
            if not STORAGE_FILE.match(str(spec.get('file', ''))):
                report.fail(f'{label}: file {spec.get("file")!r} must be a per-instance file or '
                            'a declared boot input (no host path)')
    if len(set(serials)) != len(serials):
        report.fail('guest_storage.block_devices: serials must be distinct')

    mounts = storage.get('mounts')
    if not isinstance(mounts, list) or not mounts:
        report.fail('guest_storage.mounts: missing')
        mounts = []
    forbidden = storage.get('forbidden_fstypes')
    if not isinstance(forbidden, list) or not CONTRACT_SHARE_FSTYPES <= set(forbidden):
        report.fail(f'guest_storage.forbidden_fstypes: must include {sorted(CONTRACT_SHARE_FSTYPES)}')
        forbidden = []
    forbidden_paths = storage.get('forbidden_paths')
    if not isinstance(forbidden_paths, list) or '/mnt/c' not in forbidden_paths:
        report.fail('guest_storage.forbidden_paths: must include /mnt/c (profiles P3)')
        forbidden_paths = []
    targets = set()
    for i, mount in enumerate(mounts):
        label = f'guest_storage.mounts[{i}]'
        if not isinstance(mount, dict):
            report.fail(f'{label}: must be an object')
            continue
        target, fstype = mount.get('target'), mount.get('fstype')
        if not isinstance(target, str) or not target.startswith('/'):
            report.fail(f'{label}: target must be an absolute path')
            continue
        if '*' in target.rsplit('/', 1)[0] or ('*' in target and target.rsplit('/', 1)[1] != '*'):
            report.fail(f'{label}: a wildcard is allowed only as a whole last component')
        targets.add(target)
        if not isinstance(fstype, str) or not fstype or fstype in forbidden or \
                fstype.split('.')[0] in forbidden:
            report.fail(f'{label}: file system type {fstype!r} is a share type or missing '
                        '(profiles P3)')
        if ('disk' in mount) == ('source' in mount):
            report.fail(f'{label}: name exactly one of disk or source')
        if 'disk' in mount:
            dev = devices.get(mount['disk'])
            if not isinstance(dev, dict) or dev.get('role') not in ('root', 'scratch'):
                report.fail(f'{label}: disk {mount["disk"]!r} is not the root or scratch device')
        if 'optional' in mount and (not isinstance(mount['optional'], str) or
                                    not mount['optional'].strip()):
            report.fail(f'{label}: optional must give the reason the mount may be absent')
        for path in forbidden_paths:
            if target == path or target.startswith(path.rstrip('/') + '/'):
                report.fail(f'{label}: {target} is a forbidden path')
    if mounts and not any(m.get('target') == '/' and devices.get(m.get('disk'), {}).get('role')
                          == 'root' for m in mounts if isinstance(m, dict)):
        report.fail('guest_storage.mounts: / must be on the root device')

    directories = storage.get('directories')
    if not isinstance(directories, list):
        report.fail('guest_storage.directories: missing')
        directories = []
    by_role = {}
    for i, entry in enumerate(directories):
        label = f'guest_storage.directories[{i}]'
        if not isinstance(entry, dict):
            report.fail(f'{label}: must be an object')
            continue
        by_role.setdefault(entry.get('role'), []).append(entry)
        path, mount = str(entry.get('path', '')), entry.get('mount')
        if not path.startswith('/'):
            report.fail(f'{label}: path must be absolute')
        if not entry.get('owner') or not entry.get('group'):
            report.fail(f'{label}: owner and group required')
        if not re.match(r'^[0-7]{3,4}$', str(entry.get('mode', ''))):
            report.fail(f'{label}: mode must be octal digits')
        if mount not in targets or not (mount == '/' or path.startswith(mount.rstrip('/') + '/')):
            report.fail(f'{label}: mount {mount!r} must be a declared mount that holds {path}')
    for role in DIRECTORY_ROLES:
        if len(by_role.get(role, [])) != 1:
            report.fail(f'guest_storage.directories: exactly one {role} directory required '
                        '(profiles P4)')
    if set(by_role) - set(DIRECTORY_ROLES):
        report.fail(f'guest_storage.directories: unknown roles {sorted(set(by_role) - set(DIRECTORY_ROLES))}')
    scratch_dir = (by_role.get('scratch') or [{}])[0]
    scratch_mounts = [m for m in mounts if isinstance(m, dict) and
                      m.get('target') == scratch_dir.get('mount')]
    if scratch_dir and not any(devices.get(m.get('disk'), {}).get('role') == 'scratch'
                               for m in scratch_mounts):
        report.fail('guest_storage.directories: the scratch directory must be on the scratch disk')
    exchange_dir = (by_role.get('exchange') or [{}])[0].get('path')
    declared_exchange = (profile.get('exchange') or {}).get('guest_dir')
    if declared_exchange is not None and exchange_dir != declared_exchange:
        report.fail(f'guest_storage.directories: exchange {exchange_dir!r} differs from '
                    f'exchange.guest_dir {declared_exchange!r}')
    virtio = storage.get('virtio_devices')
    if not isinstance(virtio, dict) or not all(isinstance(v, int) and not isinstance(v, bool)
                                               and v > 0 for v in virtio.values()):
        report.fail('guest_storage.virtio_devices: a map of virtio device kinds to counts')
    if provider == 'qemu':
        check_qemu_storage(report, profile, devices, virtio if isinstance(virtio, dict) else {})


def check_qemu_storage(report, profile, devices, virtio):
    """guest_storage.block_devices against launch.argv: the same nodes, files, read-only
    flags and serials, and no -blockdev or virtio-blk device that is not declared."""
    argv = (profile.get('launch') or {}).get('argv') or []
    blockdevs, blk, models = {}, [], {}
    for opt, value in qemu_options(argv):
        named = dict(split_props(value or ''))
        if opt == '-blockdev' and named.get('node-name'):
            blockdevs[named['node-name']] = named
        if opt == '-device':
            model = split_props(value or '')[0][1]
            models[model] = models.get(model, 0) + 1
            if model == 'virtio-blk-pci':
                blk.append((named.get('drive'), named.get('serial')))
    declared = {}
    for key, dev in devices.items():
        if not isinstance(dev, dict):
            continue
        for spec in block_specs(dev):
            declared[spec.get('node')] = (key, spec, 'format')
            declared[spec.get('file_node')] = (key, spec, 'file')
    for node in sorted(set(blockdevs) - set(declared)):
        report.fail(f'launch.argv: -blockdev {node} is not in guest_storage.block_devices '
                    '(profiles P4)')
    for node, (key, spec, kind) in sorted(declared.items(), key=lambda x: str(x[0])):
        props = blockdevs.get(node)
        label = f'guest_storage.block_devices.{key}'
        if props is None:
            report.fail(f'{label}: node {node} has no -blockdev in launch.argv')
            continue
        if (props.get('read-only') == 'on') != bool(spec.get('read_only')):
            report.fail(f'{label}: read_only differs from -blockdev {node} read-only')
        if kind == 'file' and props.get('filename') != spec.get('file'):
            report.fail(f'{label}: file differs from -blockdev {node} filename')
        if kind == 'format' and props.get('file') != spec.get('file_node'):
            report.fail(f'{label}: -blockdev {node} file= is not {spec.get("file_node")}')
    for key, dev in devices.items():
        if isinstance(dev, dict) and dev.get('backing'):
            props = blockdevs.get(dev.get('node')) or {}
            if props.get('backing') != dev['backing'].get('node'):
                report.fail(f'guest_storage.block_devices.{key}: backing node differs from '
                            'launch.argv')
    want = sorted((d.get('node'), d.get('serial')) for d in devices.values() if isinstance(d, dict))
    if sorted(blk, key=str) != sorted(want, key=str):
        report.fail(f'launch.argv: virtio-blk devices {sorted(blk, key=str)} differ from '
                    f'guest_storage.block_devices {want}')
    counts = {'block': models.get('virtio-blk-pci', 0), 'net': models.get('virtio-net-pci', 0),
              'entropy': models.get('virtio-rng-pci', 0)}
    if virtio and virtio != {k: v for k, v in counts.items() if v}:
        report.fail(f'guest_storage.virtio_devices {virtio} differs from launch.argv {counts}')


def check_exchange(report, profile):
    """exchange: the guest directory, the staging location and the transfer bounds."""
    ex = profile.get('exchange')
    if ex is None:
        if (profile.get('provider') or {}).get('name') == 'qemu':
            report.fail('exchange: missing (lifecycle exchange push and pull)')
        return
    if not isinstance(ex, dict):
        report.fail('exchange: must be an object')
        return
    if not str(ex.get('guest_dir', '')).startswith('/'):
        report.fail('exchange.guest_dir: must be an absolute guest path')
    if not str(ex.get('host_staging', '')).startswith(('{instance_dir}/', '{state_dir}/')):
        report.fail('exchange.host_staging: must be under {instance_dir} or {state_dir} '
                    '(never an Owner repository)')
    for part in ('push', 'pull'):
        bounds = ex.get(part)
        if not isinstance(bounds, dict):
            report.fail(f'exchange.{part}: missing')
            continue
        keys = ('max_bytes', 'max_commits') if part == 'push' else ('max_bytes',)
        for key in keys:
            value = bounds.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                report.fail(f'exchange.{part}.{key}: must be a positive integer')
        if part == 'push' and bounds.get('refs') != 1:
            report.fail('exchange.push.refs: a push carries exactly one branch')
        pattern = bounds.get('name_pattern')
        try:
            ok = isinstance(pattern, str) and pattern.startswith('^') and pattern.endswith('$') \
                and not any(re.fullmatch(pattern, bad) for bad in ('a/b', 'a\\b', '..', '.', ''))
        except re.error:
            ok = False
        if not ok:
            report.fail(f'exchange.{part}.name_pattern: must be an anchored pattern that admits '
                        'no path separator, "." or ".."')


# --- QEMU -----------------------------------------------------------------

def qemu_options(argv):
    options, index = [], 0
    while index < len(argv):
        item = argv[index]
        if not item.startswith('-'):
            options.append((None, item))
            index += 1
        elif item in QEMU_FLAGS or index + 1 >= len(argv) or argv[index + 1].startswith('-'):
            options.append((item, None))
            index += 1
        else:
            options.append((item, argv[index + 1]))
            index += 2
    return options


def split_props(value):
    """QEMU option properties: 'a,b=c' -> [('', 'a'), ('b', 'c')]; ',,' is a literal comma."""
    parts = re.split(r'(?<!,),(?!,)', value)
    out = []
    for part in parts:
        key, sep, val = part.partition('=')
        out.append((key, val) if sep else ('', key))
    return out


def size_mib(text):
    match = re.match(r'^(\d+)([MG]?)$', text)
    if not match:
        return None
    number, unit = int(match.group(1)), match.group(2)
    return number * 1024 if unit == 'G' else number


def check_qemu(report, profile, ceilings):
    launch = profile.get('launch') or {}
    argv = launch.get('argv')
    if not isinstance(argv, list) or not all(isinstance(a, str) for a in argv):
        report.fail('launch.argv: missing')
        return
    options = qemu_options(argv)
    inputs = profile.get('boot_inputs') or {}
    per_instance = set((launch.get('per_instance_files') or {}).keys())
    chardevs, accels = {}, []
    seen = [opt for opt, _ in options]
    for required in ('-nodefaults', '-no-user-config', '-cpu', '-smp', '-m', '-display'):
        if required not in seen:
            report.fail(f'launch.argv: {required} required')
    for opt, value in options:
        if opt is None:
            report.fail(f'launch.argv: stray argument {value!r}')
            continue
        if opt not in QEMU_FLAGS and opt not in QEMU_VALUE_OPTIONS:
            report.fail(f'launch.argv: {opt} is not an allowed option (host shares, extra '
                        'devices, interfaces and monitors are refused; profiles P3, P4, P6)')
            continue
        if opt in QEMU_FLAGS:
            continue
        text = value or ''
        props = split_props(text)
        named = dict(props)
        first = props[0][1] if props and props[0][0] == '' else ''
        if 'tcg' in re.split(r'[,:=]', text.lower()):
            report.fail(f'launch.argv: {opt} {text}: TCG fallback')
        if opt == '-accel':
            accels.append(first)
        elif opt == '-machine':
            accels.extend(val for key, val in props if key == 'accel')
        elif opt == '-display' and first != 'none':
            report.fail('launch.argv: -display must be none')
        elif opt == '-device':
            check_qemu_device(report, first, named)
        elif opt == '-blockdev':
            if named.get('driver') not in QEMU_BLOCK_DRIVERS:
                report.fail(f'launch.argv: -blockdev driver {named.get("driver")!r} is not '
                            'allowed (only file, qcow2 and raw)')
            if named.get('driver') == 'file':
                check_qemu_path(report, opt, named.get('filename', ''), inputs, per_instance)
        elif opt in ('-bios', '-L', '-pidfile'):
            check_qemu_path(report, opt, text, inputs, per_instance)
        elif opt == '-netdev':
            check_qemu_net(report, opt, text)
        elif opt == '-chardev':
            chardevs[named.get('id')] = first
            if first == 'socket':
                if 'path' in named or named.get('host') != LOOPBACK:
                    report.fail(f'launch.argv: -chardev {text}: must bind to {LOOPBACK} '
                                '(profiles P7)')
            elif first == 'file':
                check_qemu_path(report, opt, named.get('path', ''), inputs, per_instance)
            else:
                report.fail(f'launch.argv: -chardev backend {first!r} is not allowed')
        elif opt == '-serial' and not text.startswith('chardev:') and text != 'none':
            report.fail(f'launch.argv: -serial {text}: must use a declared chardev')
        elif opt == '-object':
            allowed = QEMU_OBJECTS.get(first)
            if allowed is None:
                report.fail(f'launch.argv: -object {first!r} is not allowed (only a '
                            'monitor-qmp QMP monitor; profiles P3, P6)')
            else:
                extra = sorted(key for key, _ in props[1:] if key not in allowed)
                if extra or any(key == '' for key, _ in props[1:]):
                    report.fail(f'launch.argv: -object {first} property {extra or text!r} '
                                'is not allowed')
                if not named.get('id') or not named.get('chardev'):
                    report.fail(f'launch.argv: -object {first} needs id= and chardev=')
        elif opt == '-smp':
            cpus = named.get('cpus') or first
            if str(cpus) != str(ceilings.get('vcpu')):
                report.fail(f'launch.argv: -smp {text} does not match ceilings.vcpu')
        elif opt == '-m':
            if size_mib(named.get('size') or first) != ceilings.get('memory_mib'):
                report.fail(f'launch.argv: -m {text} does not match ceilings.memory_mib')
        elif opt == '-cpu' and profile.get('nested_virt_exposed') is False:
            for flag in ('vmx', 'svm'):
                if named.get(flag) != 'off' and f'-{flag}' not in text.split(','):
                    report.fail(f'launch.argv: -cpu must turn {flag} off when '
                                'nested_virt_exposed is false (profiles P12)')
    for opt, value in options:
        props = split_props(value or '') if opt == '-object' else []
        if props and props[0] == ('', 'monitor-qmp'):
            backend = chardevs.get(dict(props).get('chardev'))
            if backend != 'socket':
                report.fail('launch.argv: -object monitor-qmp must use a loopback socket '
                            'chardev')
    name = (profile.get('accelerator') or {}).get('name')
    if accels != [name]:
        report.fail(f'launch.argv: exactly one accelerator ({name}) required, found {accels} '
                    '(a second accelerator is a fallback; QEMU defaults to TCG without one)')
    files = launch.get('per_instance_files') or {}
    if not str(files.get('root.qcow2', '')).endswith(f' {ceilings.get("root_disk_gib")}G'):
        report.fail('launch.per_instance_files: root.qcow2 size does not match ceilings')
    if not str(files.get('scratch.qcow2', '')).endswith(f' {ceilings.get("scratch_disk_gib")}G'):
        report.fail('launch.per_instance_files: scratch.qcow2 size does not match ceilings')


def check_qemu_device(report, model, named):
    if model not in QEMU_DEVICES:
        report.fail(f'launch.argv: -device {model} is not allowed (only virtio block, net and '
                    'rng; no USB, audio, display, 9p, virtio-serial or passthrough)')
    if model == 'virtio-net-pci' and named.get('romfile', None) != '':
        report.fail('launch.argv: virtio-net-pci needs romfile= (an option ROM is an unpinned '
                    'boot input)')


def check_qemu_path(report, opt, value, inputs, per_instance):
    match = re.match(r'^\{input:([a-z_]+)\}$', value)
    if match:
        if match.group(1) not in inputs:
            report.fail(f'launch.argv: {opt} refers to undeclared boot input {match.group(1)}')
        return
    match = re.match(r'^\{instance_dir\}/([A-Za-z0-9._-]+)$', value)
    if match:
        name = match.group(1)
        if name.endswith(('.qcow2', '.iso', '.raw', '.img')) and name not in per_instance:
            report.fail(f'launch.argv: {opt} uses undeclared per-instance disk {name}')
        return
    if value.startswith('{qemu_prefix}/'):
        return
    report.fail(f'launch.argv: {opt} uses literal host path {value!r}; boot inputs must be '
                'declared and pinned')


def check_qemu_net(report, opt, text):
    props = split_props(text)
    backend = props[0][1] if props and props[0][0] == '' else ''
    if backend != 'user':
        report.fail(f'launch.argv: {opt} {backend}: only user-mode NAT is allowed (profiles P7)')
        return
    values = {}
    for key, val in props:
        values.setdefault(key, []).append(val)
        if key == 'hostfwd':
            rule = re.match(r'^(tcp|udp)?:([^:]*):([^-]+)-', val)
            if not rule or rule.group(2) != LOOPBACK:
                report.fail(f'launch.argv: hostfwd={val} must bind to {LOOPBACK} (profiles P7)')
        if key == 'guestfwd':
            target = val.split('-', 1)[1] if '-' in val else ''
            if target.startswith('cmd:') or not target.startswith(f'tcp:{LOOPBACK}:'):
                report.fail(f'launch.argv: guestfwd={val} must target tcp:{LOOPBACK} '
                            '(profiles P7)')
        if key in ('smb', 'tftp', 'bootfile'):
            report.fail(f'launch.argv: {key}= exposes host files (profiles P3)')
    if values.get('restrict') != ['on']:
        report.fail(f'launch.argv: {opt} needs restrict=on (profiles P7)')
    if values.get('ipv6') != ['off']:
        report.fail(f'launch.argv: {opt} needs ipv6=off (profiles P7)')


# --- Incus ----------------------------------------------------------------

def check_incus(report, profile, ceilings, root):
    entry = (profile.get('provider_files') or {}).get('incus_profile')
    if not entry or not (root / entry.get('path', '')).is_file():
        report.fail('provider_files.incus_profile: missing')
        return
    try:
        incus = load_flow_yaml(root / entry['path'])
    except ValueError as exc:
        report.fail(f'provider_files.incus_profile: not JSON-compatible YAML ({exc})')
        return
    config = incus.get('config') or {}
    for key in config:
        if key.startswith('raw.') or key == 'security.privileged':
            report.fail(f'incus profile: {key} is not allowed')
    if str(config.get('limits.cpu')) != str(ceilings.get('vcpu')):
        report.fail('incus profile: limits.cpu does not match ceilings.vcpu')
    memory = str(config.get('limits.memory', ''))
    mib = ceilings.get('memory_mib')
    if mib is None or memory not in (f'{mib}MiB', f'{mib // 1024}GiB' if mib % 1024 == 0 else ''):
        report.fail('incus profile: limits.memory does not match ceilings.memory_mib')
    if profile.get('nested_virt_exposed') is False and config.get('security.nesting') != 'false':
        report.fail('incus profile: security.nesting must be "false" (profiles P12)')
    devices = incus.get('devices') or {}
    root_disks = 0
    for name, device in devices.items():
        kind = device.get('type')
        if kind not in INCUS_DEVICE_TYPES:
            report.fail(f'incus profile: device {name} of type {kind} is not allowed')
        if kind == 'disk':
            if device.get('path') == '/':
                root_disks += 1
                if device.get('size') != f'{ceilings.get("root_disk_gib")}GiB':
                    report.fail('incus profile: root disk size does not match ceilings')
                if 'source' in device:
                    report.fail(f'incus profile: root disk {name} must not have a source')
            elif device.get('source') not in INCUS_ISO_SOURCES:
                report.fail(f'incus profile: disk device {name} is a host share '
                            '(profiles P3, P4)')
        if kind == 'nic':
            if not device.get('network') or device.get('nictype') or device.get('parent'):
                report.fail(f'incus profile: nic {name} must attach to a managed network only '
                            '(never bridged onto the LAN)')
        if kind == 'proxy':
            listen = str(device.get('listen', ''))
            if not listen.startswith(f'tcp:{LOOPBACK}:'):
                report.fail(f'incus profile: proxy {name} must listen on {LOOPBACK} '
                            '(profiles P7)')
    if root_disks != 1:
        report.fail('incus profile: exactly one root disk device required')


# --- driver ---------------------------------------------------------------

def check(profile, root=REPO):
    """Check one parsed profile against the contract. Returns a Report."""
    report = Report(profile.get('name', '<unnamed>'))
    properties = json.loads((root / 'profiles' / 'properties.json').read_text(encoding='utf-8'))
    if profile.get('schema') != SCHEMA:
        report.fail(f'schema: expected {SCHEMA}')
    check_labels(report, profile, properties)
    check_status(report, profile)
    check_accelerator(report, profile)
    check_provider(report, profile, root)
    check_boot_inputs(report, profile, root)
    ceilings = check_ceilings(report, profile)
    check_state_dir(report, profile)
    check_lifecycle(report, profile, properties)
    check_network(report, profile, properties, root)
    check_isolation(report, profile)
    check_guest_storage(report, profile)
    check_exchange(report, profile)
    provider = (profile.get('provider') or {}).get('name')
    if provider == 'qemu':
        check_qemu(report, profile, ceilings)
    elif provider == 'incus':
        check_incus(report, profile, ceilings, root)
    else:
        report.fail(f'provider: {provider!r} has no configuration check')
    return report


def find_profiles(root, given):
    if not given:
        return sorted((root / 'profiles').glob('*/profile.json'))
    paths = []
    for item in given:
        path = Path(item)
        paths.append(path / 'profile.json' if path.is_dir() else path)
    return paths


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('profiles', nargs='*', help='profile directories or profile.json files')
    parser.add_argument('--strict', action='store_true',
                        help='also fail on inputs declared with an unknown pin')
    parser.add_argument('--root', default=str(REPO), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    root = Path(args.root)
    paths = find_profiles(root, args.profiles)
    if not paths:
        print('FAIL no profiles found')
        return 1
    failed = False
    for path in paths:
        try:
            profile = json.loads(Path(path).read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            print(f'FAIL {path}: cannot read ({exc})')
            failed = True
            continue
        report = check(profile, root)
        if Path(path).parent.name != profile.get('name'):
            report.fail(f'name: {profile.get("name")!r} differs from its directory')
        for message in report.errors:
            print(f'FAIL {report.name}: {message}')
        for message in report.unresolved:
            print(f'UNRESOLVED {report.name}: {message}')
        bad = bool(report.errors) or (args.strict and bool(report.unresolved))
        failed = failed or bad
        verdict = 'FAIL' if bad else 'PASS'
        note = f' ({len(report.unresolved)} unresolved pin(s))' if report.unresolved else ''
        print(f'{verdict} {report.name}{note}')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
