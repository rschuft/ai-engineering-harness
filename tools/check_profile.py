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
- a provisioning block (F-04.1b) bounds the upload, names the root step's paths and
  declares Moby with no TCP socket, its data root on scratch, root-owned sockets closed
  to others, the locked docker.io version and a local immutable image tag;
- its agent_server block (F-04.1 slice (c)) installs the lock's release binary under a
  no-login service user, binds 127.0.0.1 only, configures the decision 0001 s2 runtime
  with the local image and explicit caps inside the ceilings, keeps every data path on
  declared scratch directories and the secrets in a root-only file, and pins the
  disposable conversation fixture; with ``--openapi FILE`` the fixture is also validated
  against the locked openapi.json (a standard-library JSON Schema subset); its admission
  block declares the container guard (S-01.3.1) and the container egress guard in Moby's
  DOCKER-USER chain (S-01.4: the declared rules, both families, the container bridges, the
  same seeded unit, and an allowlist of the classes the profile enables for containers);
- ceilings are declared and match the provider configuration (profiles P2);
- exactly one accelerator and no TCG fallback (contract section 4);
- the lifecycle is the contract's closed set (contract section 3).

A boot input that cannot be known without the provider (for example firmware
shipped by an Incus server) may be declared with ``"pin_status": "unknown"`` and an
``unpinned_reason``. Such inputs are reported as UNRESOLVED; ``--strict`` fails on
them. Anything else unpinned is a FAIL.

Usage (from the repository root):
    python -I -B tools/check_profile.py [--strict] [--openapi FILE] [PROFILE ...]

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
# Directories present only on a provisioned instance (F-04.1): Moby's data root and the
# root step's state. Each carries "provisioned_only": true.
PROVISIONED_DIRECTORY_ROLES = ('moby-data-root', 'provisioning-state', 'facts-request')
# The Agent Server's scratch directories (F-04.1 slice (c)): several, each provisioned_only,
# on the scratch disk and owned by its service user.
AGENT_SERVER_ROLE = 'agent-server'
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
        if any('*' in part and part != '*' for part in target.split('/')):
            report.fail(f'{label}: a wildcard is allowed only as a whole path component')
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
        if any('provisioned_only' in e for e in by_role.get(role, [])):
            report.fail(f'guest_storage.directories: the {role} directory is never provisioned_only')
    known = set(DIRECTORY_ROLES) | set(PROVISIONED_DIRECTORY_ROLES) | {AGENT_SERVER_ROLE}
    if set(by_role) - known:
        report.fail(f'guest_storage.directories: unknown roles {sorted(set(by_role) - known)}')
    server_dirs = by_role.get(AGENT_SERVER_ROLE, [])
    scratch_disk_targets = {m.get('target') for m in mounts if isinstance(m, dict) and
                            devices.get(m.get('disk'), {}).get('role') == 'scratch'}
    for entry in server_dirs:
        if entry.get('provisioned_only') is not True or entry.get('mount') not in scratch_disk_targets \
                or entry.get('owner') in ('root', 'agent'):
            report.fail(f'guest_storage.directories: the {AGENT_SERVER_ROLE} directory '
                        f'{entry.get("path")} must be provisioned_only, on the scratch disk and '
                        'owned by the service user (neither root nor agent)')
    if server_dirs and not isinstance((profile.get('provisioning') or {}).get('agent_server'), dict):
        report.fail(f'guest_storage.directories: {AGENT_SERVER_ROLE} directories need '
                    'provisioning.agent_server')
    if len({e.get('path') for e in server_dirs}) != len(server_dirs):
        report.fail(f'guest_storage.directories: repeated {AGENT_SERVER_ROLE} path')
    for role in PROVISIONED_DIRECTORY_ROLES:
        entries = by_role.get(role, [])
        if len(entries) > 1 or any(e.get('provisioned_only') is not True for e in entries):
            report.fail(f'guest_storage.directories: at most one {role} directory, marked '
                        'provisioned_only: true')
        if entries and not isinstance(profile.get('provisioning'), dict):
            report.fail(f'guest_storage.directories: a {role} directory needs a provisioning block')
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


LOCAL_TAG = re.compile(r'^[a-z0-9]+(?:[._/-][a-z0-9]+)*:[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$')
PROVISION_UPLOAD_ROLES = {'deb', 'image-archive', 'release-binary'}


def check_provisioning(report, profile, root=REPO):
    """provisioning (F-04.1b, decision 0006): the upload bounds, the root step's paths, and
    the declared Moby configuration: unix socket only (no hosts), data root on the scratch
    disk as a provisioned_only directory, no-new-privileges, the server version of the
    locked docker.io, root-owned sockets closed to others, agent never in group docker and
    a local immutable image tag."""
    conf = profile.get('provisioning')
    if conf is None:
        return
    if not isinstance(conf, dict):
        report.fail('provisioning: must be an object')
        return
    provider = profile.get('provider') or {}
    if not isinstance(provider.get('provision_lock'), dict):
        report.fail('provisioning: needs provider.provision_lock')

    def positive(label, value):
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            report.fail(f'provisioning.{label}: must be a positive integer')

    def absolute(label, value):
        if not isinstance(value, str) or not value.startswith('/') or '..' in value.split('/'):
            report.fail(f'provisioning.{label}: must be an absolute guest path')

    storage = profile.get('guest_storage') or {}
    directories = [d for d in storage.get('directories') or [] if isinstance(d, dict)]
    up = conf.get('upload') or {}
    absolute('upload.guest_dir', up.get('guest_dir'))
    scratch = [d.get('path') for d in directories if d.get('role') == 'scratch']
    if scratch and not str(up.get('guest_dir', '')).startswith(str(scratch[0]).rstrip('/') + '/'):
        report.fail('provisioning.upload.guest_dir: must be inside the agent scratch directory')
    if not re.match(r'^[A-Za-z0-9][A-Za-z0-9._-]*$', str(up.get('ready_marker', ''))):
        report.fail('provisioning.upload.ready_marker: must be one file name')
    if not isinstance(up.get('roles'), list) or not set(up['roles']) <= PROVISION_UPLOAD_ROLES:
        report.fail(f'provisioning.upload.roles: a subset of {sorted(PROVISION_UPLOAD_ROLES)}')
    for key in ('max_files', 'max_bytes', 'timeout_s'):
        positive(f'upload.{key}', up.get(key))
    step = conf.get('root_step') or {}
    for key in ('script', 'manifest', 'staging', 'result'):
        absolute(f'root_step.{key}', step.get(key))
    positive('root_step.timeout_s', step.get('timeout_s'))
    facts = conf.get('facts') or {}
    absolute('facts.path', facts.get('path'))
    if not str(facts.get('path', '')).startswith('/run/'):
        report.fail('provisioning.facts.path: the boot-time report lives on /run (per boot)')
    moby = conf.get('moby') or {}
    daemon = moby.get('daemon_json')
    if not isinstance(daemon, dict):
        report.fail('provisioning.moby.daemon_json: must be an object')
        daemon = {}
    for key in ('hosts', 'tls', 'tlsverify', 'insecure-registries', 'registry-mirrors'):
        if key in daemon:
            report.fail(f'provisioning.moby.daemon_json: {key} is not allowed (unix socket only, '
                        'no registry; profiles P6, P7)')
    if daemon.get('no-new-privileges') is not True:
        report.fail('provisioning.moby.daemon_json: no-new-privileges must be true')
    for key, field in (('data-root', 'data_root'), ('default-runtime', 'default_runtime'),
                       ('storage-driver', 'storage_driver')):
        if daemon.get(key) != moby.get(field):
            report.fail(f'provisioning.moby.daemon_json: {key} differs from moby.{field}')
    data_roots = [d for d in directories if d.get('role') == 'moby-data-root']
    scratch_targets = {m.get('target') for m in storage.get('mounts') or []
                       if isinstance(m, dict) and m.get('disk') == 'scratch'}
    if [d.get('path') for d in data_roots] != [moby.get('data_root')]:
        report.fail('provisioning.moby.data_root: must be the moby-data-root directory of '
                    'guest_storage')
    elif data_roots[0].get('mount') not in scratch_targets:
        report.fail('provisioning.moby.data_root: must be on the scratch disk')
    sockets = moby.get('sockets')
    if not isinstance(sockets, list) or not sockets:
        report.fail("provisioning.moby.sockets: must list the guest's own sockets")
        sockets = []
    for i, entry in enumerate(sockets):
        mode = str((entry or {}).get('mode', '')) if isinstance(entry, dict) else ''
        if not isinstance(entry, dict) or not str(entry.get('path', '')).startswith('/run/') or                 entry.get('owner') != 'root' or entry.get('group') not in ('root', 'docker') or                 not re.match(r'^[0-7]{3}$', mode) or int(mode, 8) & 0o007:
            report.fail(f'provisioning.moby.sockets[{i}]: a /run socket owned by root, group '
                        'root or docker, no access for others (profiles P6)')
    sysctl = moby.get('sysctl') or {}
    if sysctl.get('path') != '/etc/sysctl.d/90-aieh-moby.conf' or \
            'net.ipv6.conf.docker0.disable_ipv6 = 1' not in str(sysctl.get('content', '')).splitlines():
        report.fail('provisioning.moby.sysctl: /etc/sysctl.d/90-aieh-moby.conf must turn IPv6 off '
                    'on docker0 (profiles P7)')
    containerd = moby.get('containerd_config') or {}
    if containerd.get('path') != '/etc/containerd/config.toml' or \
            'disabled_plugins = ["io.containerd.grpc.v1.cri"]' not in \
            str(containerd.get('content', '')).splitlines():
        report.fail('provisioning.moby.containerd_config: /etc/containerd/config.toml must turn '
                    "containerd's CRI plugin (a TCP listener) off")
    if moby.get('agent_in_docker_group') is not False:
        report.fail('provisioning.moby.agent_in_docker_group: must be false (decision 0006)')
    if not isinstance(moby.get('required_security_options'), list) or             'name=no-new-privileges' not in moby['required_security_options']:
        report.fail('provisioning.moby.required_security_options: must include '
                    'name=no-new-privileges')
    tag = str((conf.get('image') or {}).get('local_tag', ''))
    repo = tag.split(':')[0]
    if not LOCAL_TAG.match(tag) or tag.endswith(':latest') or '.' in repo.split('/')[0] or             '/' not in repo:
        report.fail('provisioning.image.local_tag: a local repository:tag with no registry '
                    'host and no "latest"')
    if 'agent_server' in conf:
        check_agent_server(report, profile, root, conf)
    entry = provider.get('provision_lock') or {}
    try:
        lock = json.loads((root / entry['path']).read_text(encoding='utf-8'))
    except (OSError, ValueError, KeyError, TypeError):
        return                                   # reported by check_provision_lock
    docker = [p for p in (lock.get('debian') or {}).get('packages') or []
              if p.get('name') == 'docker.io']
    if len(docker) != 1 or str(docker[0].get('version', '')).rsplit('-', 1)[0] !=             moby.get('server_version'):
        report.fail('provisioning.moby.server_version: must be the upstream version of the '
                    'locked docker.io')


AGENT_SERVER_SECRET_VARS = ['OH_SECRET_KEY', 'OH_SESSION_API_KEYS_0']
# Config fields that are secrets or that would send data out of the guest: never in the
# non-secret config of an inspection-only server (decision 0006, Owner authorization).
AGENT_SERVER_FORBIDDEN_CONFIG = ('session_api_keys', 'secret_key', 'previous_secret_keys',
                                 'web_url', 'app_backend_public_url', 'registered_marketplaces',
                                 'allow_cors_origins', 'allow_cors_origin_regex',
                                 'trust_forwarded_headers', 'deferred_init')
AGENT_SERVER_PATH_FIELDS = ('conversations_path', 'workspace_path', 'bash_events_dir',
                            'conversation_worktree_root')
AGENT_SERVER_PATH_ENV = ('OH_PERSISTENCE_DIR', 'HOME', 'TMPDIR')
AGENT_SERVER_HARDENING = ('NoNewPrivileges=yes', 'CapabilityBoundingSet=', 'ProtectSystem=strict',
                          'ProtectHome=yes', 'PrivateDevices=yes', 'IPAddressDeny=any',
                          'IPAddressAllow=localhost', 'UMask=0077')
MEMORY_SIZE = re.compile(r'^(\d+)([kmg])$')


def memory_mib(text):
    match = MEMORY_SIZE.match(str(text))
    if not match:
        return None
    return int(match.group(1)) * {'k': 1 / 1024, 'm': 1, 'g': 1024}[match.group(2)]


def check_agent_server(report, profile, root, conf):
    """provisioning.agent_server (F-04.1 slice (c), decisions 0001 and 0006): the release
    binary of the lock, a no-login service user in group docker (never agent), a
    127.0.0.1-only listener, the decision 0001 s2 configuration with the local immutable
    image and explicit caps inside the guest ceilings, every data path on the declared
    scratch directories, secrets only in a root-only file, the session key's custody,
    no LLM, webhook or telemetry, and the pinned conversation fixture."""
    server = conf.get('agent_server')
    if not isinstance(server, dict):
        report.fail('provisioning.agent_server: must be an object')
        return
    label = 'provisioning.agent_server'
    dirs = {d.get('path') for d in (profile.get('guest_storage') or {}).get('directories') or []
            if isinstance(d, dict) and d.get('role') == AGENT_SERVER_ROLE}
    if not dirs:
        report.fail(f'{label}: needs {AGENT_SERVER_ROLE} directories in guest_storage')
    binary = server.get('binary') or {}
    try:
        lock = json.loads((root / (profile.get('provider') or {})['provision_lock']['path'])
                          .read_text(encoding='utf-8'))
        release = lock.get('release_binary') or {}
    except (OSError, ValueError, KeyError, TypeError):
        release = {}
    if binary.get('upload_name') != release.get('name') or not release.get('name'):
        report.fail(f'{label}.binary.upload_name: must be the provision lock\'s release_binary')
    if binary.get('owner') != 'root' or binary.get('group') != 'root' or binary.get('mode') != '755' \
            or not str(binary.get('path', '')).startswith('/opt/'):
        report.fail(f'{label}.binary: root:root 755 under /opt')
    if server.get('version') and release.get('name') and \
            f"-{server['version']}-" not in release['name']:
        report.fail(f'{label}.version: differs from the release binary of the lock')
    user = server.get('user') or {}
    if user.get('name') in (None, '', 'root', 'agent') or user.get('groups') != ['docker'] or \
            user.get('shell') not in ('/usr/sbin/nologin', '/bin/false') or \
            user.get('system') is not True or user.get('home') not in dirs:
        report.fail(f'{label}.user: a system user (not root, not agent) with no login shell, '
                    'only group docker and its home in an agent-server directory')
    if ((conf.get('moby') or {}).get('agent_in_docker_group')) is not False:
        report.fail(f'{label}: agent must stay outside group docker')
    listener = server.get('listener') or {}
    port = listener.get('port')
    if listener.get('address') != LOOPBACK or not isinstance(port, int) or isinstance(port, bool) \
            or not 1024 <= port <= 65535:
        report.fail(f'{label}.listener: 127.0.0.1 and an unprivileged port (profiles P7)')
    service = server.get('service') or {}
    if service.get('argv') != ['--host', LOOPBACK, '--port', str(port)]:
        report.fail(f'{label}.service.argv: must bind --host 127.0.0.1 --port <listener.port> '
                    'explicitly (1.60.1 binds 0.0.0.0 by default once a session key is set)')
    options = (service.get('hardening') or {}).get('options') or []
    missing = [o for o in AGENT_SERVER_HARDENING if o not in options]
    if missing or not (service.get('hardening') or {}).get('justification'):
        report.fail(f'{label}.service.hardening: needs {missing} and a justification')
    cfg_entry = server.get('config') or {}
    cfg = cfg_entry.get('content')
    if not isinstance(cfg, dict):
        report.fail(f'{label}.config.content: must be an object')
        cfg = {}
    if cfg_entry.get('owner') != 'root' or cfg_entry.get('mode') not in ('644', '640'):
        report.fail(f'{label}.config: root-owned, readable by the service user')
    if cfg.get('conversation_runtime') != 'docker' or cfg.get('conversation_runtime_selectable') \
            is not False:
        report.fail(f'{label}.config: conversation_runtime docker, conversation_runtime_selectable '
                    'false (decision 0001 s2)')
    if cfg.get('conversation_image') != (conf.get('image') or {}).get('local_tag'):
        report.fail(f'{label}.config.conversation_image: must be provisioning.image.local_tag '
                    '(decision 0006 item 3)')
    ceilings = profile.get('ceilings') or {}
    mem = memory_mib(cfg.get('conversation_container_memory'))
    cpus = cfg.get('conversation_container_cpus')
    pids = cfg.get('conversation_container_pids_limit')
    runs = cfg.get('max_concurrent_runs')
    if mem is None or not isinstance(cpus, (int, float)) or isinstance(cpus, bool) or cpus <= 0 \
            or not isinstance(pids, int) or isinstance(pids, bool) or pids <= 0 or \
            not isinstance(runs, int) or isinstance(runs, bool) or runs <= 0:
        report.fail(f'{label}.config: explicit conversation_container_memory, _cpus, _pids_limit '
                    'and max_concurrent_runs (decision 0001 s3)')
    elif mem * runs >= ceilings.get('memory_mib', 0) or cpus * runs >= ceilings.get('vcpu', 0):
        report.fail(f'{label}.config: max_concurrent_runs x the per-conversation caps must stay '
                    'inside the guest ceilings (decision 0001 s3)')
    for key in AGENT_SERVER_FORBIDDEN_CONFIG:
        if key in cfg:
            report.fail(f'{label}.config: {key} is not allowed (secret or outbound)')
    if cfg.get('webhooks') not in (None, []) or \
            (cfg.get('telemetry') or {}).get('exporter', 'none') != 'none' or \
            cfg.get('enable_vscode') is not False or cfg.get('preload_tools') is not False:
        report.fail(f'{label}.config: no webhook, telemetry exporter none, no VSCode, no tool '
                    'preload')
    if any(k in json.dumps(cfg).lower() for k in ('api_key', '"llm', 'posthog_api_key')):
        report.fail(f'{label}.config: no LLM or credential setting')
    for key in AGENT_SERVER_PATH_FIELDS:
        if cfg.get(key) not in dirs:
            report.fail(f'{label}.config.{key}: must be an agent-server directory on scratch')
    env = server.get('environment') or {}
    for key in AGENT_SERVER_PATH_ENV:
        if env.get(key) not in dirs:
            report.fail(f'{label}.environment.{key}: must be an agent-server directory on scratch')
    if env.get('OPENHANDS_AGENT_SERVER_CONFIG_PATH') != cfg_entry.get('path'):
        report.fail(f'{label}.environment: OPENHANDS_AGENT_SERVER_CONFIG_PATH must be the config path')
    if any(k.startswith('OH_') and k != 'OH_PERSISTENCE_DIR' for k in env) or \
            any(k in env for k in AGENT_SERVER_SECRET_VARS):
        report.fail(f'{label}.environment: no OH_* override and no secret (secrets live in the '
                    'environment file)')
    secrets = server.get('secrets') or {}
    if secrets.get('owner') != 'root' or secrets.get('group') != 'root' or \
            secrets.get('mode') != '600' or secrets.get('variables') != AGENT_SERVER_SECRET_VARS:
        report.fail(f'{label}.secrets: a root:root 600 environment file holding '
                    f'{AGENT_SERVER_SECRET_VARS}')
    key = server.get('session_key') or {}
    if key.get('owner') != 'root' or key.get('group') != 'agent' or key.get('mode') != '440' or \
            not str(key.get('host_path', '')).startswith('{instance_dir}/'):
        report.fail(f'{label}.session_key: root:agent 440 in the guest, exported only into '
                    '{instance_dir} (profiles P5)')
    fixture = server.get('fixture') or {}
    check_repo_file(report, root, f'{label}.fixture', fixture)
    openapi = fixture.get('openapi') or {}
    if openapi.get('sha256') != locked_openapi_sha256(root):
        report.fail(f'{label}.fixture.openapi.sha256: must be the locked openapi.json '
                    '(composition/lock/components.lock.json release_assets)')
    if 'conversations' in server:
        check_conversations(report, profile, server)
    if 'admission' in server:
        check_admission(report, profile, root, conf, server)
    if 'jobs' in server:
        check_jobs(report, conf, server)
    try:
        body = json.loads((root / fixture['path']).read_text(encoding='utf-8'))
    except (OSError, ValueError, KeyError, TypeError):
        return                                   # reported by check_repo_file
    for problem in fixture_problems(body):
        report.fail(f'{label}.fixture: {problem}')


# The 1.60.1 Docker runtime's mount targets inside a conversation container
# (docker_runtime/registry.py _CONVERSATIONS_DIR, _PERSISTENCE_DIR, _WORKSPACE_DIR).
CONVERSATION_MOUNT_DESTINATIONS = ['/var/openhands/.openhands',
                                   '/var/openhands/conversations/{conversation_hex}', '/workspace']
CONVERSATION_FORBIDDEN_SOURCES = ('/run/docker.sock', '/var/run/docker.sock', '/run/containerd',
                                  '/srv/scratch/docker', '/etc/aieh', '/var/lib/aieh')
CONVERSATION_DEVIATIONS = ['host-gateway', 'no-network-none', 'request-caps-override']


def check_conversations(report, profile, server):
    """provisioning.agent_server.conversations (F-04.2): the declared conversation container
    (decision 0001 s2/s3, decision 0006 item 3): mounts only from agent-server directories on
    scratch and never a socket, Moby's data root or a secret path; cap-drop ALL and
    no-new-privileges; a 127.0.0.1-only port binding; the recorded deviations; and the
    on-demand facts (a root:agent request directory, a /run report, a bounded rate)."""
    conv = server.get('conversations')
    label = 'provisioning.agent_server.conversations'
    if not isinstance(conv, dict):
        report.fail(f'{label}: must be an object')
        return
    dirs = {d.get('path') for d in (profile.get('guest_storage') or {}).get('directories') or []
            if isinstance(d, dict) and d.get('role') == AGENT_SERVER_ROLE}
    root = str(conv.get('source_root', ''))
    if root not in dirs:
        report.fail(f'{label}.source_root: must be an agent-server directory')
    mounts = conv.get('mounts')
    if not isinstance(mounts, list) or not mounts:
        report.fail(f'{label}.mounts: must list the declared mounts')
        mounts = []
    forbidden = conv.get('forbidden_sources') or []
    if not set(CONVERSATION_FORBIDDEN_SOURCES) <= set(forbidden):
        report.fail(f'{label}.forbidden_sources: must include {list(CONVERSATION_FORBIDDEN_SOURCES)}')
    for i, m in enumerate(mounts):
        source = str((m or {}).get('source', '')) if isinstance(m, dict) else ''
        if not isinstance(m, dict) or m.get('type') != 'bind' or m.get('rw') not in (True, False) or \
                not source.startswith(root.rstrip('/') + '/') or '..' in source.split('/') or \
                any(source == f or source.startswith(f.rstrip('/') + '/') for f in forbidden):
            report.fail(f'{label}.mounts[{i}]: a bind mount whose source is under source_root and '
                        'no forbidden path (decision 0001 s3)')
    if sorted(str((m or {}).get('destination')) for m in mounts if isinstance(m, dict)) != \
            sorted(CONVERSATION_MOUNT_DESTINATIONS):
        report.fail(f'{label}.mounts: the destinations must be the 1.60.1 Docker runtime\'s '
                    f'{CONVERSATION_MOUNT_DESTINATIONS}')
    if conv.get('cap_drop') != ['ALL'] or 'no-new-privileges' not in (conv.get('security_opt') or []):
        report.fail(f'{label}: cap_drop [ALL] and security_opt no-new-privileges')
    published = conv.get('published') or {}
    if published.get('host_ip') != LOOPBACK or published.get('container_port') != \
            f"{(server.get('listener') or {}).get('port')}/tcp":
        report.fail(f'{label}.published: the container port on 127.0.0.1 only (profiles P7)')
    if not conv.get('owner_label') or not conv.get('listener_rule'):
        report.fail(f'{label}: owner_label and listener_rule required')
    if sorted(d.get('id') for d in conv.get('deviations') or [] if isinstance(d, dict)) != \
            sorted(CONVERSATION_DEVIATIONS) or not all(
                d.get('carried_to') for d in conv.get('deviations') or [] if isinstance(d, dict)):
        report.fail(f'{label}.deviations: record {CONVERSATION_DEVIATIONS}, each carried to '
                    'later leaves (decision 0001 s3)')
    facts = conv.get('facts') or {}
    request = str(facts.get('request', ''))
    request_dirs = [d for d in (profile.get('guest_storage') or {}).get('directories') or []
                    if isinstance(d, dict) and d.get('role') == 'facts-request']
    if len(request_dirs) != 1 or request.rsplit('/', 1)[0] != request_dirs[0].get('path') or \
            request_dirs[0].get('owner') != 'root' or request_dirs[0].get('group') != 'agent' or \
            request_dirs[0].get('mode') != '730':
        report.fail(f'{label}.facts.request: a file in the root:agent 730 facts-request directory')
    if not str(facts.get('report', '')).startswith('/run/'):
        report.fail(f'{label}.facts.report: the on-demand report lives on /run')
    rate = facts.get('rate') or {}
    if not all(isinstance(rate.get(k), int) and not isinstance(rate.get(k), bool) and rate[k] > 0
               for k in ('interval_s', 'burst')) or rate.get('burst', 0) > 60:
        report.fail(f'{label}.facts.rate: a positive interval and a burst of at most 60')


def locked_openapi_sha256(root):
    try:
        lock = json.loads((root / 'composition' / 'lock' / 'components.lock.json')
                          .read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    found = [a.get('sha256') for a in lock.get('release_assets') or []
             if a.get('component') == 'openhands-agent-server' and a.get('name') == 'openapi.json']
    return found[0] if len(found) == 1 else None


UUID_TEXT = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')
FIXTURE_KEYS = {'conversation_id', 'conversation_runtime', 'workspace', 'agent_settings',
                'autotitle', 'container', 'tags'}
ROUTES_SCHEMA = 'ai-engineering-harness/profiles/agent-server-routes/v1'
ROUTE_METHODS = ('GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS', 'WEBSOCKET')
ROUTE_ADMISSIONS = ('public', 'session-key', 'session-key-or-bearer', 'init-key',
                    'session-key-or-workspace-cookie', 'app-backend-session',
                    'first-message-session-key')
ROUTE_CLASSES = ('public-read', 'management-read', 'privileged')
ROUTE_WS_VARIANTS = ('no_auth_message', 'first_message_wrong_key', 'query_wrong_key',
                     'header_wrong_key')
# S-01.3.1: the container guard's rules as the profile must declare them (iptables syntax;
# the seeded aieh-container-guard installs exactly these, in this order)
GUARD_RULES = ['-m conntrack --ctstate RELATED,ESTABLISHED -j RETURN',
               '-m limit --limit 10/min --limit-burst 20 -j LOG --log-prefix '
               '"aieh-container-guard: "',
               '-p tcp -j REJECT --reject-with tcp-reset',
               '-j REJECT']
# S-01.4: the egress guard in Moby's DOCKER-USER chain (same script and unit as the guard):
# its own chain with the same four rules under its own log prefix, entered for a packet from
# a container bridge that leaves by another interface; DOCKER-USER ends with RETURN.
EGRESS_HOOK = 'DOCKER-USER'
EGRESS_LOG_PREFIX = 'aieh-egress-guard: '
EGRESS_RULES = ['-m conntrack --ctstate RELATED,ESTABLISHED -j RETURN',
                '-m limit --limit 10/min --limit-burst 20 -j LOG --log-prefix '
                '"aieh-egress-guard: "',
                '-p tcp -j REJECT --reject-with tcp-reset',
                '-j REJECT']
# the endpoint classes a container may be allowed to reach (profiles P7)
CONTAINER_CLASSES = ('inference', 'provision')


def route_problems(data):
    """The route inventory of provisioning.agent_server.admission (S-01.3.1): every route
    has a method, a path, a known credential kind, class, source and dispatcher use, and an
    expected refusal; a public route is a GET of class public-read; a route that needs a
    credential is never expected to answer 2xx without one, and a WebSocket route never to
    stay open (101 without a close); no route appears twice."""
    problems = []
    if not isinstance(data, dict) or data.get('schema') != ROUTES_SCHEMA:
        return [f'schema must be {ROUTES_SCHEMA}']
    routes = data.get('routes')
    if not isinstance(routes, list) or not routes:
        return ['routes must be a non-empty list']
    seen = set()
    for i, r in enumerate(routes):
        if not isinstance(r, dict) or r.get('method') not in ROUTE_METHODS or \
                not str(r.get('path', '')).startswith('/'):
            problems.append(f'routes[{i}]: an object with a known method and an absolute path')
            continue
        method, where = r['method'], f"{r['method']} {r['path']}"
        if (method, r['path']) in seen:
            problems.append(f'{where}: listed twice')
        seen.add((method, r['path']))
        if r.get('admission') not in ROUTE_ADMISSIONS:
            problems.append(f'{where}: admission must be one of {list(ROUTE_ADMISSIONS)}')
        if r.get('class') not in ROUTE_CLASSES:
            problems.append(f'{where}: class must be one of {list(ROUTE_CLASSES)}')
        if r.get('dispatcher') not in ('allowed', 'validation', 'not-used'):
            problems.append(f'{where}: dispatcher must be allowed, validation or not-used')
        if r.get('source') not in ('openapi', 'framework', 'binary'):
            problems.append(f'{where}: source must be openapi, framework or binary')
        public = r.get('admission') == 'public'
        if public != (r.get('class') == 'public-read'):
            problems.append(f'{where}: admission public and class public-read go together')
        if public and method != 'GET':
            problems.append(f'{where}: a public route must be a GET')
        expect = r.get('expect')
        if not isinstance(expect, dict) or not expect:
            problems.append(f'{where}: expect must name the refusal')
        elif method == 'WEBSOCKET':
            if public or not (set(expect) == {'handshake'} or
                              set(expect) == set(ROUTE_WS_VARIANTS)):
                problems.append(f'{where}: a WebSocket route needs a credential and expects '
                                f'handshake or {list(ROUTE_WS_VARIANTS)}')
            elif any(v == 101 or not isinstance(v, int) for v in expect.values()):
                problems.append(f'{where}: a WebSocket refusal is a close code or a refused '
                                'handshake, never 101')
        elif set(expect) != {'no_key', 'wrong_key'}:
            problems.append(f'{where}: expect no_key and wrong_key')
        elif not public and any(not isinstance(v, int) or 200 <= v < 300
                                for v in expect.values()):
            problems.append(f'{where}: a route that needs a credential must not answer 2xx '
                            'without one')
    return problems


def check_admission(report, profile, root, conf, server):
    """provisioning.agent_server.admission (S-01.3.1): the pinned route inventory, the
    session-key header and the fail-closed start check, the container guard (chain, both
    families, docker0 and the bridges, the declared rules, Moby requires it) and icc off on
    Moby's default bridge."""
    label = 'provisioning.agent_server.admission'
    adm = server.get('admission')
    if not isinstance(adm, dict):
        report.fail(f'{label}: must be an object')
        return
    entry = adm.get('routes') or {}
    check_repo_file(report, root, f'{label}.routes', entry)
    try:
        data = json.loads((root / entry['path']).read_text(encoding='utf-8'))
    except (OSError, ValueError, KeyError, TypeError):
        data = None
    if data is not None:
        for problem in route_problems(data):
            report.fail(f'{label}.routes: {problem}')
        if isinstance(data, dict) and data.get('version') != server.get('version'):
            report.fail(f'{label}.routes: version must be the Agent Server version')
    key = adm.get('session_key') or {}
    if key.get('header') != 'X-Session-API-Key' or \
            not str(key.get('start_check', '')).startswith('/usr/local/sbin/'):
        report.fail(f'{label}.session_key: header X-Session-API-Key and a seeded start check '
                    'under /usr/local/sbin (fail closed without a key)')
    guard = (adm.get('network') or {}).get('guard') or {}
    if guard.get('rules') != GUARD_RULES:
        report.fail(f'{label}.network.guard.rules: must be {GUARD_RULES}')
    if not re.match(r'^[A-Z][A-Z0-9-]{2,28}$', str(guard.get('chain', ''))) or \
            guard.get('families') != ['iptables', 'ip6tables'] or \
            'docker0' not in (guard.get('interfaces') or []) or \
            guard.get('log_prefix') != 'aieh-container-guard: ' or \
            not str(guard.get('script', '')).startswith('/usr/local/sbin/') or \
            not str(guard.get('docker_dropin', '')).startswith(
                '/etc/systemd/system/docker.service.d/') or \
            not str(guard.get('unit', '')).endswith('.service'):
        report.fail(f'{label}.network.guard: an INPUT chain for both families on docker0 and '
                    'the bridges, the declared log prefix, a seeded script and unit, and a '
                    'docker.service drop-in')
    daemon = (conf.get('moby') or {}).get('daemon_json') or {}
    if daemon.get('icc') is not False:
        report.fail(f'{label}: provisioning.moby.daemon_json must set icc false (no '
                    'container-to-container connection on the default bridge)')
    check_egress_guard(report, profile, guard, (adm.get('network') or {}).get('egress_guard'),
                       daemon, f'{label}.network.egress_guard')
    dispatcher = adm.get('dispatcher') or {}
    if not dispatcher.get('principal') or not dispatcher.get('bootstrap') or \
            not dispatcher.get('owner_ui'):
        report.fail(f'{label}.dispatcher: name the principal, the bootstrap performer and the '
                    'Owner UI path (planned or unknown)')


def enabled_container_classes(profile):
    """The endpoint classes the profile enables for containers: network.endpoints of class
    inference or provision whose status is not deferred."""
    return sorted({str(e.get('class')) for e in (profile.get('network') or {}).get('endpoints') or []
                   if isinstance(e, dict) and e.get('class') in CONTAINER_CLASSES and
                   not str(e.get('status', '')).startswith('deferred')})


def check_egress_guard(report, profile, guard, egress, daemon, label):
    """provisioning.agent_server.admission.network.egress_guard (S-01.4): Moby's DOCKER-USER
    chain sends a packet from a container bridge that leaves by another interface to the
    guard's own chain (the declared four rules, its own log prefix), DOCKER-USER ends with
    RETURN, both families, the same seeded script and unit as the container guard (so Moby
    requires it), and an allowlist that names only classes the profile enables for
    containers (empty while none is). Moby keeps managing iptables and IP forwarding."""
    if not isinstance(egress, dict):
        report.fail(f'{label}: must be declared (S-01.4: container egress, fail closed)')
        return
    chain = str(egress.get('chain', ''))
    interfaces = egress.get('interfaces') if isinstance(egress.get('interfaces'), list) else []
    if egress.get('rules') != EGRESS_RULES:
        report.fail(f'{label}.rules: must be {EGRESS_RULES}')
    if not re.match(r'^[A-Z][A-Z0-9-]{2,28}$', chain) or chain in (guard.get('chain'), EGRESS_HOOK):
        report.fail(f'{label}.chain: its own chain, not the container guard\'s or {EGRESS_HOOK}')
    if egress.get('hook') != EGRESS_HOOK:
        report.fail(f'{label}.hook: must be {EGRESS_HOOK} (FORWARD jumps to it first)')
    if 'docker0' not in interfaces or interfaces != (guard.get('interfaces') or []):
        report.fail(f'{label}.interfaces: the container guard\'s bridges, docker0 included')
    want_hooks = [f'-i {i} ! -o {i} -j {chain}' for i in interfaces] + ['-j RETURN']
    if egress.get('hook_rules') != want_hooks:
        report.fail(f'{label}.hook_rules: must be {want_hooks}')
    if egress.get('families') != ['iptables', 'ip6tables']:
        report.fail(f'{label}.families: iptables and ip6tables')
    if egress.get('log_prefix') != EGRESS_LOG_PREFIX:
        report.fail(f'{label}.log_prefix: must be {EGRESS_LOG_PREFIX!r}')
    if egress.get('script') != guard.get('script') or egress.get('unit') != guard.get('unit'):
        report.fail(f'{label}: installed by the container guard\'s script and unit, which '
                    'docker.service requires (fail closed)')
    allow = egress.get('allowlist')
    enabled = enabled_container_classes(profile)
    if not isinstance(allow, list):
        report.fail(f'{label}.allowlist: must be a list')
    else:
        for n, entry in enumerate(allow):
            if not isinstance(entry, dict) or entry.get('class') not in enabled or \
                    not str(entry.get('rule', '')).endswith('-j RETURN'):
                report.fail(f'{label}.allowlist[{n}]: an entry names a class the profile enables '
                            f'for containers ({enabled or "none"}) and a rule ending -j RETURN')
    for key in ('allowlist_rule', 'rule', 'dockerd', 'fail_closed'):
        if not egress.get(key):
            report.fail(f'{label}.{key}: required')
    if daemon.get('iptables') is False or daemon.get('ip-forward') is False:
        report.fail(f'{label}: provisioning.moby.daemon_json must not turn off iptables or '
                    'ip-forward (S-01.4 ruling R5)')


# The job environment (S-01.3.2): what every conversation container must show, and the CI
# constraints carried to the runner containment leaves.
JOB_HOST_CONFIG = {'Privileged': False, 'CapDrop': ['ALL'], 'CapAdd': [],
                   'SecurityOpt': ['no-new-privileges'], 'AppArmorProfile': 'docker-default',
                   'IpcMode': 'private', 'CgroupnsMode': 'private', 'PidMode': '', 'UTSMode': '',
                   'UsernsMode': '', 'Devices': [], 'DeviceCgroupRules': [], 'GroupAdd': [],
                   'Sysctls': {}, 'VolumesFrom': [], 'Links': [], 'Mounts': []}
JOB_ENGINE_SOCKETS = ('/run/docker.sock', '/var/run/docker.sock', '/run/containerd/containerd.sock')
JOB_ENGINE_PORTS = (2375, 2376)
JOB_REQUIRED_SECURITY_OPTIONS = ('name=no-new-privileges', 'name=apparmor',
                                 'name=seccomp,profile=builtin')
JOB_CI_CONSTRAINTS = ['no-engine-endpoint', 'no-privileged-credential', 'not-privileged',
                      'no-host-path']
JOB_CI_CARRIED_TO = ('Q-02.2.1', 'Q-02.2.2', 'Q-02.3.2')
JOB_ENGINE_ENV = re.compile(r'(?i)^(DOCKER|CONTAINERD|CONTAINER_HOST|PODMAN|BUILDKIT)')


def check_jobs(report, conf, server):
    """provisioning.agent_server.jobs (S-01.3.2): the job environment's declared hardening
    (exact HostConfig values with no unconfined or disabled option, the process rule, the
    engine sockets and ports, the credential names), the Moby defaults it relies on, no
    engine variable for the server's docker CLI, the browser off, and the CI constraints
    carried as planned to the runner containment leaves."""
    label = 'provisioning.agent_server.jobs'
    jobs = server.get('jobs')
    if not isinstance(jobs, dict):
        report.fail(f'{label}: must be an object')
        return
    host = jobs.get('host_config') if isinstance(jobs.get('host_config'), dict) else {}
    for key, want in JOB_HOST_CONFIG.items():
        if host.get(key) != want:
            report.fail(f'{label}.host_config.{key}: must be {json.dumps(want)}')
    loose = [o for o in host.get('SecurityOpt') or [] if re.search(
        r'(?i)unconfined|disable|privileged|seccomp|apparmor|label|systempaths', str(o))]
    if loose:
        report.fail(f'{label}.host_config.SecurityOpt: no confinement option may be overridden '
                    f'({loose})')
    env = jobs.get('environment') if isinstance(jobs.get('environment'), dict) else {}
    try:
        pattern = re.compile(str(env.get('credential_name_pattern', '')), re.I)
    except re.error:
        pattern = None
    if env.get('secret_names') != ['OH_SECRET_KEY', 'OH_SESSION_API_KEYS_0'] or pattern is None or \
            not all(pattern.search(n) for n in ('DOCKER_HOST', 'CONTAINERD_ADDRESS', 'GITEA_TOKEN',
                                                'OH_SECRET_KEY', 'PASSWORD')):
        report.fail(f'{label}.environment: secret_names are the conversation keys only, and the '
                    'credential name pattern matches engine and credential names')
    proc = jobs.get('process') if isinstance(jobs.get('process'), dict) else {}
    if proc.get('capabilities') != '0' * 16 or proc.get('no_new_privs') != '1' or \
            proc.get('seccomp') != '2' or not str(proc.get('apparmor', '')).startswith(
                'docker-default'):
        report.fail(f'{label}.process: no capability, no_new_privs 1, seccomp 2 and AppArmor '
                    'docker-default inside the container')
    sockets = jobs.get('engine_sockets') if isinstance(jobs.get('engine_sockets'), list) else []
    if not set(JOB_ENGINE_SOCKETS) <= set(sockets) or \
            not all(str(s).startswith(('/run/', '/var/run/')) for s in sockets):
        report.fail(f'{label}.engine_sockets: /run paths including {list(JOB_ENGINE_SOCKETS)}')
    if not set(JOB_ENGINE_PORTS) <= set(jobs.get('engine_tcp_ports') or []):
        report.fail(f'{label}.engine_tcp_ports: must include {list(JOB_ENGINE_PORTS)}')
    alias = jobs.get('host_alias') if isinstance(jobs.get('host_alias'), dict) else {}
    if '10.0.2.2' not in (alias.get('addresses') or []) or \
            not {'{ssh_port}', '{qmp_port}'} <= set(alias.get('host_ports') or []):
        report.fail(f'{label}.host_alias: 10.0.2.2 with the instance\'s SSH forward and QMP ports')
    try:
        files = re.compile(str(jobs.get('credential_files', '')))
    except re.error:
        files = None
    if files is None or not all(files.search(n) for n in ('.git-credentials', 'session.key',
                                                          'secrets.env', 'id_ed25519')):
        report.fail(f'{label}.credential_files: a pattern naming the credential files')
    for key in ('socket_rule', 'tcp_rule', 'routes_rule', 'token_rule', 'fail_closed', 'probe'):
        if not jobs.get(key):
            report.fail(f'{label}.{key}: required')
    sources = jobs.get('sources') if isinstance(jobs.get('sources'), dict) else {}
    if not all(sources.get(k) for k in ('server', 'server_config', 'moby')):
        report.fail(f'{label}.sources: name what the server sets, its configuration and the '
                    'Moby defaults')
    if sorted((jobs.get('deviations') or {})) != ['host-gateway', 'no-network-none']:
        report.fail(f'{label}.deviations: host-gateway and no-network-none, each carried')
    moby = conf.get('moby') or {}
    if (moby.get('daemon_json') or {}).get('no-new-privileges') is not True or \
            not set(JOB_REQUIRED_SECURITY_OPTIONS) <= set(moby.get('required_security_options') or []):
        report.fail(f'{label}: Moby must default no-new-privileges and require '
                    f'{list(JOB_REQUIRED_SECURITY_OPTIONS)}')
    if any(JOB_ENGINE_ENV.search(k) for k in server.get('environment') or {}):
        report.fail(f'{label}: the server environment may not set an engine variable (the '
                    "server's docker CLI inherits it)")
    if ((server.get('config') or {}).get('content') or {}).get('enable_browser') is not False:
        report.fail(f'{label}: provisioning.agent_server.config enable_browser must be false')
    ci = jobs.get('ci') if isinstance(jobs.get('ci'), dict) else {}
    if ci.get('status') != 'planned' or \
            [c.get('id') for c in ci.get('constraints') or [] if isinstance(c, dict)] != \
            JOB_CI_CONSTRAINTS or not all(c.get('rule') for c in ci.get('constraints') or []
                                          if isinstance(c, dict)) or \
            not set(JOB_CI_CARRIED_TO) <= set(ci.get('carried_to') or []):
        report.fail(f'{label}.ci: status planned, the constraints {JOB_CI_CONSTRAINTS} and '
                    f'carried to {list(JOB_CI_CARRIED_TO)}')


CREDENTIAL_KEYS = re.compile(r'(?i)(api_?key|secret|password|token|credential|auth)')


def fixture_problems(body):
    """Structural rules for the disposable conversation create (F-04.1, for F-04.2):
    Docker runtime, a fixed id, no initial message, no LLM credential or secret, one agent
    source, the server-provisioned workspace and no override of the container caps."""
    if not isinstance(body, dict):
        return ['must be one JSON object']
    problems = []
    if set(body) - FIXTURE_KEYS:
        problems.append(f'unexpected fields {sorted(set(body) - FIXTURE_KEYS)}')
    if body.get('conversation_runtime') != 'docker':
        problems.append('conversation_runtime must be "docker" (decision 0001 s2)')
    if not UUID_TEXT.match(str(body.get('conversation_id', ''))):
        problems.append('conversation_id must be a fixed lowercase UUID')
    if 'initial_message' in body:
        problems.append('no initial message')
    sources = [k for k in ('agent', 'agent_settings', 'agent_profile_id') if k in body]
    if sources != ['agent_settings']:
        problems.append('exactly one agent source: agent_settings')
    if body.get('workspace') != {'kind': 'LocalWorkspace', 'working_dir': '/workspace'}:
        problems.append('workspace must be the server-provisioned /workspace (no host path)')
    container = body.get('container')
    if container is not None and (not isinstance(container, dict) or
                                  {'memory', 'cpus'} & set(container)):
        problems.append('container must not override the memory or CPU caps')
    settings = body.get('agent_settings') if isinstance(body.get('agent_settings'), dict) else {}
    if 'llm' in settings:
        problems.append('agent_settings: no llm block (no LLM credential)')

    def walk(value, path):
        if isinstance(value, dict):
            for k, v in value.items():
                if CREDENTIAL_KEYS.search(str(k)):
                    problems.append(f'{path}.{k}: no credential or secret field')
                walk(v, f'{path}.{k}')
        elif isinstance(value, list):
            for i, v in enumerate(value):
                walk(v, f'{path}[{i}]')
    walk(body, '$')
    return problems


# A standard-library subset of JSON Schema (2020-12, as OpenAPI 3.1 uses it), enough for
# the request schemas of the locked Agent Server API. An assertion keyword outside the
# subset is an error (fail closed), never silently ignored.
SCHEMA_ANNOTATIONS = {'title', 'description', 'default', 'examples', 'example', 'deprecated',
                      'readOnly', 'writeOnly', 'discriminator', 'x-nullable', '$schema', '$id',
                      'contentMediaType', 'contentEncoding'}
SCHEMA_SUPPORTED = {'$ref', 'type', 'enum', 'const', 'anyOf', 'oneOf', 'allOf', 'properties',
                    'required', 'additionalProperties', 'items', 'pattern', 'format',
                    'minLength', 'maxLength', 'minimum', 'maximum', 'exclusiveMinimum',
                    'exclusiveMaximum', 'minItems', 'maxItems', 'propertyNames'}
JSON_TYPES = {'object': dict, 'array': list, 'string': str, 'boolean': bool}


def _type_ok(value, name):
    if name == 'null':
        return value is None
    if name == 'integer':
        return isinstance(value, int) and not isinstance(value, bool)
    if name == 'number':
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    expected = JSON_TYPES.get(name)
    return expected is not None and isinstance(value, expected) and \
        (name != 'boolean' or isinstance(value, bool))


def schema_errors(value, schema, document, path='$', depth=0):
    """Errors of value against schema; $ref resolves inside document ('#/...')."""
    if depth > 64:
        return [f'{path}: schema nesting deeper than 64']
    if schema is True or schema == {}:
        return []
    if schema is False:
        return [f'{path}: not allowed']
    if not isinstance(schema, dict):
        return [f'{path}: unusable schema']
    errors = []
    unknown = set(schema) - SCHEMA_SUPPORTED - SCHEMA_ANNOTATIONS
    if unknown:
        return [f'{path}: unsupported schema keywords {sorted(unknown)} (subset validator)']
    if '$ref' in schema:
        ref = schema['$ref']
        if not str(ref).startswith('#/'):
            return [f'{path}: only local references are supported ({ref})']
        target = document
        for part in ref[2:].split('/'):
            part = part.replace('~1', '/').replace('~0', '~')
            if not isinstance(target, dict) or part not in target:
                return [f'{path}: unresolvable reference {ref}']
            target = target[part]
        errors += schema_errors(value, target, document, path, depth + 1)
    if 'type' in schema:
        names = schema['type'] if isinstance(schema['type'], list) else [schema['type']]
        if not any(_type_ok(value, n) for n in names):
            return errors + [f'{path}: expected type {names}']
    if 'const' in schema and value != schema['const']:
        errors.append(f'{path}: must be {schema["const"]!r}')
    if 'enum' in schema and value not in schema['enum']:
        errors.append(f'{path}: must be one of {schema["enum"]!r}')
    for key in ('anyOf', 'oneOf'):
        if key in schema:
            passing = [b for b in schema[key] if not schema_errors(value, b, document, path, depth + 1)]
            if not passing or (key == 'oneOf' and len(passing) != 1):
                errors.append(f'{path}: {len(passing)} of the {key} branches match')
    for branch in schema.get('allOf') or []:
        errors += schema_errors(value, branch, document, path, depth + 1)
    if isinstance(value, str):
        if 'pattern' in schema and not re.search(schema['pattern'], value):
            errors.append(f'{path}: does not match {schema["pattern"]!r}')
        if schema.get('format') == 'uuid' and not UUID_TEXT.match(value.lower()):
            errors.append(f'{path}: not a UUID')
        if len(value) < schema.get('minLength', 0) or len(value) > schema.get('maxLength', len(value)):
            errors.append(f'{path}: length out of bounds')
    if _type_ok(value, 'number'):
        for key, ok in (('minimum', lambda b: value >= b), ('maximum', lambda b: value <= b),
                        ('exclusiveMinimum', lambda b: value > b),
                        ('exclusiveMaximum', lambda b: value < b)):
            if key in schema and not ok(schema[key]):
                errors.append(f'{path}: {key} {schema[key]}')
    if isinstance(value, dict):
        for name in schema.get('required') or []:
            if name not in value:
                errors.append(f'{path}: missing required {name!r}')
        props = schema.get('properties') or {}
        extra = schema.get('additionalProperties', True)
        for name, item in value.items():
            if 'propertyNames' in schema:
                errors += schema_errors(name, schema['propertyNames'], document,
                                        f'{path}.<name {name}>', depth + 1)
            if name in props:
                errors += schema_errors(item, props[name], document, f'{path}.{name}', depth + 1)
            elif extra is False:
                errors.append(f'{path}: additional property {name!r} not allowed')
            elif isinstance(extra, dict):
                errors += schema_errors(item, extra, document, f'{path}.{name}', depth + 1)
    if isinstance(value, list):
        if len(value) < schema.get('minItems', 0) or len(value) > schema.get('maxItems', len(value)):
            errors.append(f'{path}: item count out of bounds')
        if 'items' in schema:
            for i, item in enumerate(value):
                errors += schema_errors(item, schema['items'], document, f'{path}[{i}]', depth + 1)
    return errors


def validate_fixture_openapi(profile, root, openapi_path):
    """The pinned fixture against the locked openapi.json (a downloaded file, never
    committed): its sha256 must equal both pins, then the request schema is applied with
    the subset validator. Returns (ok, lines)."""
    server = (profile.get('provisioning') or {}).get('agent_server') or {}
    fixture = server.get('fixture') or {}
    pin = (fixture.get('openapi') or {}).get('sha256')
    data = Path(openapi_path).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != pin or digest != locked_openapi_sha256(root):
        return False, [f'{openapi_path}: sha256 {digest} is not the locked openapi.json {pin}']
    document = json.loads(data.decode('utf-8'))
    body = json.loads((root / fixture['path']).read_text(encoding='utf-8'))
    ref = (fixture.get('openapi') or {}).get('schema', '')
    errors = schema_errors(body, {'$ref': ref}, document)
    request = (((document.get('paths') or {}).get('/api/conversations') or {}).get('post') or {})
    used = (((request.get('requestBody') or {}).get('content') or {}).get('application/json')
            or {}).get('schema', {}).get('$ref')
    if used != ref:
        errors.append(f'POST /api/conversations takes {used}, the profile names {ref}')
    lines = [f'openapi {document.get("info", {}).get("version")} sha256 {digest}',
             f'fixture {fixture["path"]} against {ref}: ' + ('valid' if not errors else
                                                            f'{len(errors)} error(s)')]
    return not errors, lines + errors


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
    check_provisioning(report, profile, root)
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
    parser.add_argument('--openapi', metavar='FILE',
                        help='the downloaded openapi.json of the locked Agent Server release: '
                             'also validate the conversation fixture against it (F-04.1)')
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
        if args.openapi and isinstance((profile.get('provisioning') or {}).get('agent_server'), dict):
            try:
                ok, lines = validate_fixture_openapi(profile, root, args.openapi)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                ok, lines = False, [f'{args.openapi}: cannot validate ({exc})']
            for line in lines:
                print(f'{"OPENAPI" if ok else "FAIL"} {report.name}: {line}')
            if not ok:
                report.fail('provisioning.agent_server.fixture: not valid against the locked openapi.json')
        bad = bool(report.errors) or (args.strict and bool(report.unresolved))
        failed = failed or bad
        verdict = 'FAIL' if bad else 'PASS'
        note = f' ({len(report.unresolved)} unresolved pin(s))' if report.unresolved else ''
        print(f'{verdict} {report.name}{note}')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
