"""Check the versioned containment case catalogue (plan leaf S-02.1).

``security/containment-cases.json`` is the expected-denial matrix of the job environment:
every case names a category (file, sibling-workspace, secret, socket, egress,
privilege-expansion, management-api), the principal it runs as, the exact non-destructive
attempt, the outcome classes it expects, the enforcement location that must produce that
outcome (with references into ``profiles/properties.json``, ``policy/network-matrix.json``
and ``security/inventory.json``), and the permitted operation that pairs with it as its
positive control. ``tools/guest.py containment-probe`` runs the catalogue in a disposable
guest; ``security/README.md`` renders it. This checker enforces the leaf's acceptance
mechanically: each probe has an expected enforcement location and a positive control for
a permitted operation.

It fails when:

- a category has no denial case, or the catalogue has an unknown key, kind, status,
  category, enforcement location, snapshot key or requirement;
- a case that is not itself a permitted control names no enforcement location, an
  enforcement location names no reference, or a reference does not resolve (a profiles
  P-id, a network-matrix edge id, an inventory asset, credential or finding id); a case
  names no protected asset, or its principal, assets or carried findings do not exist;
- a case that is not a permitted control names no positive control, or its control is not
  an existing permitted case; a permitted case names a control;
- the expected outcomes are empty, a denial expects a success outcome, a permitted case
  expects anything but success, or a deviation names no compensating case;
- a probe names an unknown source, operation or extractor, or misses an argument;
- an attempt is not provably non-destructive: an operation outside the closed set, a
  write-class operation outside the probe's own scratch directories, a command that is
  deny-listed (rm, kill, mount, chmod, reboot and the like) or an engine client
  subcommand that is not read-only, a TCP connect beyond the container's own loopback,
  or an off-host target outside the approved S-01.4 sweeps;
- a path tied to the profile (``profile_value``) differs from the profile's value;
- a mutation (the live sensitivity proof) names no existing denial case or a
  non-permitted operation, or a category has no mutation;
- a machine path appears, or the README's generated block differs from ``--render``.

It needs only the standard library and reads nothing outside the repository.

Usage (from the repository root):
    python -I -B tools/check_containment_cases.py [--catalogue FILE] [--root DIR] [--list] [--render]

Exit status: 0 PASS, 1 FAIL, 2 could not run.
"""
import argparse
import importlib.util
import json
import posixpath
import re
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    'check_security_inventory', Path(__file__).resolve().parent / 'check_security_inventory.py')
csi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(csi)

SCHEMA = 'ai-engineering-harness/security/containment-cases/v1'
DEFAULT_CATALOGUE = Path('security') / 'containment-cases.json'
PROPERTIES = 'profiles/properties.json'
MATRIX = 'policy/network-matrix.json'

CATEGORIES = ('file', 'sibling-workspace', 'secret', 'socket', 'egress', 'privilege-expansion',
              'management-api')
KINDS = ('denial', 'permitted', 'hardening', 'deviation')
STATUSES = ('executable', 'planned')
VERDICTS = ('PASS', 'FAIL', 'UNKNOWN')
LOCATIONS = ('container-mount-set', 'uid-permissions', 'capabilities', 'no-new-privileges',
             'seccomp', 'apparmor', 'pid-namespace', 'device-cgroup', 'masked-proc',
             'image-content', 'container-guard', 'egress-guard', 'icc', 'slirp-restrict',
             'guest-routing', 'agent-server-key', 'key-check', 'launch-no-share')
SNAPSHOT_KEYS = ('docker_inspect', 'container_guard', 'egress_guard', 'daemon', 'pins')
REQUIREMENTS = ('egress-falsification',)
SOURCES = ('containment-probe', 'job-access-probe', 'admission-probe')

# Outcome classes that mean the attempted operation succeeded. A denial never expects one;
# a permitted control expects only these. tools/guest.py classifies with the same set.
SUCCESS_OUTCOMES = frozenset({
    'ok', 'connected', 'found', 'answered', 'answered-2xx', 'writable-found', 'share-found',
    'foreign-mem-readable', 'extra-devices', 'root-obtained', 'shared-with-peer'})

# The containment-probe's closed operation set, inside a conversation container as the
# job's default user: {op: (required args, write-class)}. A write-class operation may only
# touch the probe's own scratch directories; none sends a packet off the container.
OPS = {
    'read': (('path',), False),              # open O_RDONLY|O_NONBLOCK; regular files: read <= 4 KiB
    'list': (('path',), False),              # listdir
    'stat': (('path',), False),              # lstat
    'access-write': (('path',), False),      # access(2) W_OK: check-only, opens nothing
    'own-workspace': ((), True),             # plant, read back and list a generated canary file
    'proc-root-search': (('name',), False),  # /proc/<pid>/root/<workspace scratch>/<name>, every pid
    'mountinfo': (('check',), False),        # parse /proc/self/mountinfo
    'writable-scan': ((), False),            # access W_OK over every disk-backed mount, bounded
    'canary-scan': ((), True),               # plant a control canary, walk for the canary marker
    'unix-control': ((), True),              # bind and connect an AF_UNIX socket in scratch
    'connect-tcp': (('host', 'port'), False),  # loopback only
    'socket': (('type',), False),            # create and close an AF_INET socket (sends nothing)
    'unshare': (('flags',), False),          # in a forked child that exits at once
    'fork-control': ((), False),             # a forked child that exits 0 (the unshare plumbing)
    'mknod': (('kind',), True),              # in scratch
    'init-module': (('variant',), False),    # init_module with an empty image (cannot load)
    'ptrace-read': ((), False),              # open /proc/<own child>/mem read-only
    'proc-census': ((), False),              # processes of another uid, and their mem (RO)
    'dev-list': ((), False),                 # listdir /dev against Moby's default set
    'exec': (('argv',), False),              # a fixed, allowlisted command
    'net-ifaces': ((), False),               # /sys/class/net
}
MOUNTINFO_CHECKS = ('share', 'own-binds', 'shared-with-peer')
SOCKET_TYPES = ('raw-icmp', 'dgram-icmp')
UNSHARE_FLAGS = ('user', 'mount', 'net')
MKNOD_KINDS = ('char', 'fifo')
MODULE_VARIANTS = ('probe', 'control')
# exec: argv[0] and, for engine clients, the read-only subcommands
EXEC_ALLOWED = {'id': None, 'sudo': None, 'su': None, 'docker': ('version', 'info'),
                'ctr': ('version',)}
EXEC_EXACT = {'sudo': [['sudo', '-n', 'true'], ['sudo', '-n', 'id', '-u']],
              'su': [['su', '-c', 'true', 'root']]}
DENY_COMMANDS = re.compile(
    r'^(rm|rmdir|unlink|shred|truncate|dd|mkfs(\..*)?|kill|pkill|killall|mount|umount|'
    r'reboot|shutdown|poweroff|halt|systemctl|chmod|chown|chgrp|setfacl|sysctl|modprobe|'
    r'insmod|rmmod|ip|iptables|ip6tables|nft|tee|mv|cp|ln)$')

# The reused primitives' extractors (tools/guest.py CONTAINMENT_EXTRACTORS), with their
# required arguments.
EXTRACTORS = {
    'job-access-probe': {
        'socket': ('path',), 'sockets-found': (), 'tcp': ('what',), 'routes': (),
        'tokens': ('label',), 'credential-files': (), 'token-control': (),
        'env': ('field',), 'inspected': ('field',), 'controls': ('key',),
        'egress': ('what',), 'egress-route': (), 'trusted': ()},
    'admission-probe': {
        'sweep': (), 'network': ('what',), 'custody': (), 'keycheck': (), 'logged': (),
        'trusted': ()},
}
# Off-host traffic only through the approved S-01.4 sweeps (the route-present one needs
# the falsification guest).
OFF_HOST_EXTRACTS = {('job-access-probe', 'egress'), ('job-access-probe', 'egress-route')}
OFF_HOST = re.compile(r'(?<![\d.])(?!(?:10|127|172\.(?:1[6-9]|2\d|3[01])|192\.168|169\.254)\.)'
                      r'(?:\d{1,3}\.){3}\d{1,3}(?![\d.])')

CASE_ID = re.compile(r'^[a-z][a-z0-9]*(-[a-z0-9]+)*$')
TOP_KEYS = {'schema', 'plan_leaf', 'title', 'version', 'as_of', 'inventory', 'properties',
            'matrix', 'profile', 'readme', 'checker', 'runner', 'categories', 'kinds',
            'verdicts', 'statuses', 'enforcement_locations', 'snapshot_keys', 'scratch',
            'fingerprints', 'cases', 'mutations', 'sources', 'notes'}
CASE_KEYS = {'id', 'category', 'kind', 'name', 'principal', 'attempt', 'probe', 'expected',
             'enforcement', 'assets', 'positive_control', 'verdict_rule', 'carried', 'status',
             'depends_on', 'requires', 'compensated_by', 'verify_at', 'notes'}
PRINCIPAL_KEYS = {'id', 'user', 'root_attempt'}
PROBE_KEYS = {'source', 'op', 'extract', 'args'}
EXPECTED_KEYS = {'outcomes', 'rule'}
ENFORCEMENT_KEYS = {'location', 'refs'}
MUTATION_KEYS = {'id', 'case', 'op', 'args', 'note'}
SCRATCH_KEYS = {'container', 'workspace'}
FINGERPRINT_KEYS = {'gitea', 'source'}
GITEA_FP = re.compile(r'^sha256:[0-9a-f]{16}$')
PROPERTY_ID = re.compile(r'^P[0-9]+$')

GENERATED_BEGIN = '<!-- BEGIN GENERATED: python -I -B tools/check_containment_cases.py --render -->'
GENERATED_END = '<!-- END GENERATED: containment cases -->'


def _list(value):
    return value if isinstance(value, list) else []


def _dict(value):
    return value if isinstance(value, dict) else {}


def _str(value):
    return value if isinstance(value, str) else ''


def profile_lookup(profile, pointer):
    """The value at a dotted pointer into the profile, or None."""
    node = profile
    for part in _str(pointer).split('.'):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def under(path, roots):
    """True when the POSIX ``path`` (after normalization) is one of ``roots`` or below one."""
    if not isinstance(path, str) or not path.startswith('/') or '..' in path.split('/'):
        return False
    norm = posixpath.normpath(path)
    return any(norm == r or norm.startswith(r.rstrip('/') + '/') for r in roots)


class Checker(csi.Checker):
    """Reuses the inventory checker's id tables, link and machine-path helpers."""

    def __init__(self, catalogue, inventory, root, readme_text=None, properties=None,
                 matrix=None, profile=None, files=None):
        super().__init__(inventory, root, readme_text, files)
        self.cat = catalogue
        self.properties = _dict(properties)
        self.matrix = _dict(matrix)
        self.profile = _dict(profile)

    def keys(self, where, entry, allowed):
        for key in entry:
            if key not in allowed:
                self.add('SCHEMA', where, f'unknown key {key!r}')

    def strings(self, where, entry, key, required=False):
        value = entry.get(key, [])
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            self.add('SCHEMA', where, f'{key} must be a list of strings')
            return []
        if required and not value:
            self.add('SCHEMA', where, f'{key} must name at least one entry')
        return value

    # -- the checks --------------------------------------------------------------

    def run(self):
        c = self.cat
        if not isinstance(c, dict):
            self.add('SCHEMA', 'catalogue', 'the catalogue must be a JSON object')
            return self.problems
        if c.get('schema') != SCHEMA:
            self.add('SCHEMA', 'schema', f'expected {SCHEMA!r}')
        self.keys('catalogue', c, TOP_KEYS)
        if not isinstance(c.get('version'), str) or not c.get('version'):
            self.add('SCHEMA', 'version', 'the catalogue carries a version string')
        for key, want in (('categories', CATEGORIES), ('kinds', KINDS), ('statuses', STATUSES),
                          ('verdicts', VERDICTS), ('enforcement_locations', LOCATIONS),
                          ('snapshot_keys', SNAPSHOT_KEYS)):
            got = _dict(c.get(key))
            if sorted(got) != sorted(want) or not all(isinstance(v, str) and v.strip()
                                                      for v in got.values()):
                self.add('SCHEMA', key, f'must describe exactly {list(want)}')
        for key in ('inventory', 'properties', 'matrix', 'profile', 'readme', 'checker', 'runner'):
            if key in c:
                self.check_link(key, c.get(key))
            else:
                self.add('SCHEMA', key, 'is required')
        if not self.check_links('catalogue', c, 'sources'):
            self.add('SCHEMA', 'catalogue.sources', 'the catalogue needs source links')
        self.check_machine_paths(c, 'catalogue')
        scratch = _dict(c.get('scratch'))
        self.keys('scratch', scratch, SCRATCH_KEYS)
        self.scratch = [_str(scratch.get(k)) for k in sorted(SCRATCH_KEYS)]
        if not all(s.startswith('/') and s.count('/') >= 2 and '..' not in s for s in self.scratch):
            self.add('SCHEMA', 'scratch', 'container and workspace scratch directories are '
                     'absolute paths below a top-level directory')
        self.check_fingerprints(_dict(c.get('fingerprints')))

        self.principals = self.index('principals')
        self.assets = self.index('assets')
        self.credentials = self.index('credentials')
        self.findings = self.index('findings')
        self.plan = self.plan_ids() or set()
        self.pids = {p.get('id') for p in _list(self.properties.get('properties'))
                     if isinstance(p, dict)}
        self.edges = {e.get('id') for e in _list(self.matrix.get('edges')) +
                      _list(self.matrix.get('external_edges')) if isinstance(e, dict)}

        cases = _list(c.get('cases'))
        if not cases:
            self.add('SCHEMA', 'cases', 'must be a non-empty list')
        self.by_id = {}
        for n, case in enumerate(cases):
            where = f'cases[{n}]'
            if not isinstance(case, dict):
                self.add('SCHEMA', where, 'must be an object')
                continue
            ident = case.get('id')
            if not isinstance(ident, str) or not CASE_ID.match(ident):
                self.add('ID_INVALID', where, f'id {ident!r} must be kebab-case')
                continue
            if ident in self.by_id:
                self.add('ID_DUPLICATE', where, f'id {ident!r} is used twice')
            self.by_id[ident] = case
        for ident, case in self.by_id.items():
            self.check_case(f'cases.{ident}', case)
        for cat in CATEGORIES:
            if not any(x.get('category') == cat and x.get('kind') == 'denial'
                       for x in self.by_id.values()):
                self.add('CATEGORY_MISSING', cat, 'every category needs at least one denial case')
        self.check_mutations(_list(c.get('mutations')))
        self.check_readme_block()
        return self.problems

    def check_fingerprints(self, fps):
        self.keys('fingerprints', fps, FINGERPRINT_KEYS)
        gitea = fps.get('gitea')
        if not isinstance(gitea, dict) or not gitea:
            self.add('SCHEMA', 'fingerprints.gitea', 'the published Gitea token fingerprints '
                     '(label: sha256:<16 hex>) the secret cases search for')
            return
        for label, fp in gitea.items():
            if not re.match(r'^[A-Za-z0-9_.:-]{1,64}$', str(label)) or not \
                    (isinstance(fp, str) and GITEA_FP.match(fp)):
                self.add('SCHEMA', f'fingerprints.gitea.{label}', 'LABEL: sha256:<16 hex digits>')
        self.check_link('fingerprints.source', fps.get('source'))

    def check_case(self, where, case):
        self.keys(where, case, CASE_KEYS)
        for key in ('name', 'attempt', 'verdict_rule'):
            if not isinstance(case.get(key), str) or not case.get(key).strip():
                self.add('SCHEMA', where, f'{key} is required')
        category, kind, status = case.get('category'), case.get('kind'), case.get('status')
        if category not in CATEGORIES:
            self.add('SCHEMA', where, f'category {category!r} is not one of {CATEGORIES}')
        if kind not in KINDS:
            self.add('SCHEMA', where, f'kind {kind!r} is not one of {KINDS}')
        if status not in STATUSES:
            self.add('SCHEMA', where, f'status {status!r} is not one of {STATUSES}')
        elif status == 'planned' and not (isinstance(case.get('verify_at'), str) and
                                          case['verify_at'] in self.plan):
            self.add('STATUS_UNSUPPORTED', where, 'a planned case names the plan leaf that runs it')
        # principal
        principal = case.get('principal')
        if not isinstance(principal, dict):
            self.add('SCHEMA', where, 'principal must be an object')
        else:
            self.keys(f'{where}.principal', principal, PRINCIPAL_KEYS)
            if not isinstance(principal.get('id'), str) or principal.get('id') not in self.principals:
                self.add('DANGLING_REF', where, f"principal {principal.get('id')!r} is not an "
                         'inventory principal')
            if not isinstance(principal.get('user'), str) or not principal.get('user').strip():
                self.add('SCHEMA', where, 'principal.user names the uid:gid or account it runs as')
            if not isinstance(principal.get('root_attempt'), bool):
                self.add('SCHEMA', where, 'principal.root_attempt must be true or false')
        # assets and carried findings
        for aid in self.strings(where, case, 'assets', required=True):
            if aid not in self.assets:
                self.add('DANGLING_REF', where, f'asset {aid!r} is not an inventory asset')
        for fid in self.strings(where, case, 'carried'):
            if fid not in self.findings:
                self.add('DANGLING_REF', where, f'finding {fid!r} is not an inventory finding')
        for key in self.strings(where, case, 'depends_on'):
            if key not in SNAPSHOT_KEYS:
                self.add('SCHEMA', where, f'depends_on {key!r} is not one of {SNAPSHOT_KEYS}')
        for req in self.strings(where, case, 'requires'):
            if req not in REQUIREMENTS:
                self.add('SCHEMA', where, f'requires {req!r} is not one of {REQUIREMENTS}')
        self.check_expected(where, case, kind)
        self.check_enforcement(where, case, kind)
        self.check_control(where, case, kind)
        self.check_probe(where, case.get('probe'), case)
        if kind == 'deviation':
            comp = self.strings(where, case, 'compensated_by', required=True)
            for cid in comp:
                other = self.by_id.get(cid)
                if not isinstance(other, dict) or other.get('kind') not in ('denial', 'hardening'):
                    self.add('DEVIATION', where, f'compensated_by {cid!r} is not a denial or '
                             'hardening case')
        elif 'compensated_by' in case:
            self.add('SCHEMA', where, 'compensated_by belongs to a deviation')

    def check_expected(self, where, case, kind):
        expected = case.get('expected')
        if not isinstance(expected, dict):
            self.add('EXPECTED_INVALID', where, 'expected must be an object')
            return
        self.keys(f'{where}.expected', expected, EXPECTED_KEYS)
        outcomes = expected.get('outcomes')
        if not isinstance(outcomes, list) or not outcomes or \
                not all(isinstance(o, str) and o for o in outcomes):
            self.add('EXPECTED_INVALID', where, 'expected.outcomes is a non-empty list of '
                     'outcome classes')
            return
        if not isinstance(expected.get('rule'), str) or not expected.get('rule').strip():
            self.add('EXPECTED_INVALID', where, 'expected.rule states the outcome in words')
        success = [o for o in outcomes if o in SUCCESS_OUTCOMES]
        if kind in ('denial', 'hardening', 'deviation') and success:
            self.add('EXPECTED_INVALID', where, f'a {kind} case never expects a success outcome '
                     f'{success}')
        if kind == 'permitted' and len(success) != len(outcomes):
            self.add('EXPECTED_INVALID', where, 'a permitted control expects only success '
                     f'outcomes ({sorted(SUCCESS_OUTCOMES)})')

    def check_enforcement(self, where, case, kind):
        value = case.get('enforcement')
        if not isinstance(value, list):
            self.add('ENFORCEMENT_MISSING', where, 'enforcement must be a list')
            return
        if not value and kind != 'permitted':
            self.add('ENFORCEMENT_MISSING', where, 'a probe names its expected enforcement '
                     'location')
        for n, entry in enumerate(value):
            w = f'{where}.enforcement[{n}]'
            if not isinstance(entry, dict):
                self.add('ENFORCEMENT_MISSING', w, 'must be an object')
                continue
            self.keys(w, entry, ENFORCEMENT_KEYS)
            if entry.get('location') not in LOCATIONS:
                self.add('ENFORCEMENT_MISSING', w, f"location {entry.get('location')!r} is not "
                         f'one of {LOCATIONS}')
            refs = self.strings(w, entry, 'refs', required=True)
            for ref in refs:
                if not self.resolves(ref):
                    self.add('DANGLING_REF', w, f'reference {ref!r} resolves to no profiles '
                             'P-id, network-matrix edge, inventory asset, credential or finding')

    def resolves(self, ref):
        if PROPERTY_ID.match(ref):
            return ref in self.pids
        if ref.startswith('nm-'):
            return ref in self.edges
        return ref in self.assets or ref in self.findings or ref in self.credentials

    def check_control(self, where, case, kind):
        control = case.get('positive_control')
        if kind == 'permitted':
            if control is not None:
                self.add('CONTROL_INVALID', where, 'a permitted control names no control '
                         '(positive_control null)')
            return
        if not isinstance(control, str) or not control:
            self.add('CONTROL_MISSING', where, 'a probe names the permitted operation that '
                     'pairs with it (positive_control)')
            return
        other = self.by_id.get(control)
        if not isinstance(other, dict):
            self.add('CONTROL_MISSING', where, f'positive_control {control!r} is not a case')
        elif other.get('kind') != 'permitted':
            self.add('CONTROL_INVALID', where, f'positive_control {control!r} is not a '
                     'permitted case')
        elif other.get('status') != 'executable' and case.get('status') == 'executable':
            self.add('CONTROL_INVALID', where, f'positive_control {control!r} does not run')

    def check_probe(self, where, probe, case):
        if not isinstance(probe, dict):
            self.add('PROBE_INVALID', where, 'probe must be an object')
            return
        self.keys(f'{where}.probe', probe, PROBE_KEYS)
        source, args = probe.get('source'), probe.get('args', {})
        if not isinstance(args, dict):
            self.add('PROBE_INVALID', where, 'probe.args must be an object')
            args = {}
        if source not in SOURCES:
            self.add('PROBE_INVALID', where, f'source {source!r} is not one of {SOURCES}')
            return
        text = json.dumps(probe, sort_keys=True) + ' ' + _str(case.get('attempt'))
        if OFF_HOST.search(text) and (source, _str(probe.get('extract'))) not in OFF_HOST_EXTRACTS:
            self.add('DESTRUCTIVE', where, 'an off-host target is only attempted by the '
                     'approved S-01.4 sweeps')
        if source == 'containment-probe':
            if 'extract' in probe:
                self.add('PROBE_INVALID', where, 'a containment-probe case names an op')
            self.check_op(where, probe.get('op'), args)
        else:
            if 'op' in probe:
                self.add('PROBE_INVALID', where, f'a {source} case names an extract')
            table = EXTRACTORS[source]
            extract = probe.get('extract')
            if not isinstance(extract, str) or extract not in table:
                self.add('PROBE_INVALID', where, f'extract {extract!r} is not one of '
                         f'{sorted(table)}')
            else:
                for arg in table[extract]:
                    if not isinstance(args.get(arg), str) or not args.get(arg):
                        self.add('PROBE_INVALID', where, f'extract {extract} needs {arg}')
            if (source, extract) == ('job-access-probe', 'egress-route') and \
                    'egress-falsification' not in _list(case.get('requires')):
                self.add('DESTRUCTIVE', where, 'the route-present sweep requires '
                         'egress-falsification')
        pointer = args.get('profile_value')
        if pointer is not None:
            value = profile_lookup(self.profile, pointer)
            if not isinstance(value, str) or value != args.get('path'):
                self.add('PROFILE_VALUE', where, f'path {args.get("path")!r} is not the '
                         f'profile value {pointer} ({value!r})')

    def check_op(self, where, op, args):
        if not isinstance(op, str) or op not in OPS:
            self.add('DESTRUCTIVE', where, f'op {op!r} is not in the closed operation set '
                     f'{sorted(OPS)}')
            return
        required, write = OPS[op]
        for arg in required:
            if arg not in args:
                self.add('PROBE_INVALID', where, f'op {op} needs {arg}')
        if write and any(k in args for k in ('path', 'name', 'dir')):
            self.add('DESTRUCTIVE', where, f'the write-class op {op} touches only the probe\'s '
                     'own scratch directories; it takes no path')
        path = args.get('path')
        if path is not None and (not isinstance(path, str) or not path.startswith('/')):
            self.add('PROBE_INVALID', where, f'path {path!r} is an absolute guest path')
        if op == 'mountinfo' and args.get('check') not in MOUNTINFO_CHECKS:
            self.add('PROBE_INVALID', where, f'mountinfo check is one of {MOUNTINFO_CHECKS}')
        if op == 'socket' and args.get('type') not in SOCKET_TYPES:
            self.add('PROBE_INVALID', where, f'socket type is one of {SOCKET_TYPES}')
        if op == 'unshare':
            flags = args.get('flags')
            if not isinstance(flags, list) or any(f not in UNSHARE_FLAGS for f in flags):
                self.add('PROBE_INVALID', where, f'unshare flags are a list of {UNSHARE_FLAGS}')
        if op == 'mknod' and args.get('kind') not in MKNOD_KINDS:
            self.add('PROBE_INVALID', where, f'mknod kind is one of {MKNOD_KINDS}')
        if op == 'init-module' and args.get('variant') not in MODULE_VARIANTS:
            self.add('PROBE_INVALID', where, f'init-module variant is one of {MODULE_VARIANTS}')
        if op == 'connect-tcp':
            port = args.get('port')
            if args.get('host') != '127.0.0.1' or not isinstance(port, int) or \
                    not 0 < port < 65536:
                self.add('DESTRUCTIVE', where, 'connect-tcp reaches only the container\'s own '
                         'loopback (127.0.0.1) at a port number')
        if op == 'exec':
            self.check_exec(where, args.get('argv'))
        for key, value in args.items():
            if key in ('path', 'name') and isinstance(value, str) and \
                    re.search(r'[\x00\n]', value):
                self.add('PROBE_INVALID', where, f'{key} holds a control character')

    def check_exec(self, where, argv):
        if not isinstance(argv, list) or not argv or not all(isinstance(a, str) and a for a in argv):
            self.add('PROBE_INVALID', where, 'exec argv is a non-empty list of strings')
            return
        name = posixpath.basename(argv[0])
        if DENY_COMMANDS.match(name) or name not in EXEC_ALLOWED:
            self.add('DESTRUCTIVE', where, f'exec {name!r} is not an allowlisted, '
                     'non-destructive command')
            return
        if name in EXEC_EXACT and argv not in EXEC_EXACT[name]:
            self.add('DESTRUCTIVE', where, f'exec {argv} is not one of the fixed forms '
                     f'{EXEC_EXACT[name]}')
        sub = EXEC_ALLOWED[name]
        if sub is not None and (len(argv) < 2 or argv[1] not in sub):
            self.add('DESTRUCTIVE', where, f'{name} runs only a read-only subcommand {sub}')

    def check_mutations(self, mutations):
        seen, categories = set(), set()
        for n, m in enumerate(mutations):
            where = f'mutations[{n}]'
            if not isinstance(m, dict):
                self.add('MUTATION_INVALID', where, 'must be an object')
                continue
            self.keys(where, m, MUTATION_KEYS)
            ident = m.get('id')
            if not isinstance(ident, str) or not CASE_ID.match(ident) or ident in seen:
                self.add('MUTATION_INVALID', where, f'id {ident!r} must be a new kebab-case id')
            seen.add(_str(ident))
            case = self.by_id.get(_str(m.get('case')))
            if not isinstance(case, dict) or case.get('kind') != 'denial':
                self.add('MUTATION_INVALID', where, f"case {m.get('case')!r} is not a denial case")
            else:
                categories.add(case.get('category'))
            args = m.get('args', {})
            if not isinstance(args, dict):
                self.add('MUTATION_INVALID', where, 'args must be an object')
                args = {}
            self.check_op(where, m.get('op'), args)
            if not isinstance(m.get('note'), str) or not m.get('note').strip():
                self.add('MUTATION_INVALID', where, 'note says what the mutation points the '
                         'case at')
        for cat in CATEGORIES:
            if cat not in categories:
                self.add('MUTATION_MISSING', cat, 'every category needs a live sensitivity '
                         'mutation')

    def check_readme_block(self):
        if self.readme is None:
            return
        if csi.MACHINE_PATH.search(self.readme):
            self.add('MACHINE_PATH', 'readme', 'a machine-specific path must not be published')
        block = generated_block(self.readme)
        if block is None:
            self.add('README_STALE', 'readme', 'the generated containment block is missing its '
                     'markers')
        elif block.strip() != render(self.cat).strip():
            self.add('README_STALE', 'readme', 'the generated containment block differs from '
                     '--render; re-render it from the catalogue')


def generated_block(text):
    start = text.find(GENERATED_BEGIN)
    if start < 0:
        return None
    end = text.find(GENERATED_END, start)
    if end < 0:
        return None
    return text[start + len(GENERATED_BEGIN):end]


def _cell(value):
    return str(value).replace('|', '\\|').replace('\n', ' ')


def _ids(values):
    values = [str(v) for v in _list(values)]
    return ', '.join(f'`{v}`' for v in values) if values else '-'


def probe_text(probe):
    probe = _dict(probe)
    if probe.get('source') == 'containment-probe':
        head = f"containment-probe `{probe.get('op')}`"
    else:
        head = f"{probe.get('source')} `{probe.get('extract')}`"
    args = _dict(probe.get('args'))
    shown = {k: v for k, v in args.items() if k != 'profile_value'}
    return head + (f" {json.dumps(shown, sort_keys=True)}" if shown else '')


def render(catalogue):
    """The README's generated block: the summary and the expected-denial matrix."""
    cat = _dict(catalogue)
    cases = [x for x in _list(cat.get('cases')) if isinstance(x, dict)]
    out = ['', f"Catalogue version {cat.get('version')} ({len(cases)} cases).", '',
           '| Category | Denial | Hardening | Deviation | Permitted controls |',
           '|---|---|---|---|---|']
    for c in CATEGORIES:
        counts = [sum(1 for x in cases if x.get('category') == c and x.get('kind') == k)
                  for k in ('denial', 'hardening', 'deviation', 'permitted')]
        out.append(f'| {c} | ' + ' | '.join(str(n) for n in counts) + ' |')
    out += ['', '### Expected-denial matrix', '',
            '| Case | Category | Kind | Principal | Attempt | Probe | Expected | Enforcement | '
            'Positive control | Carried |',
            '|---|---|---|---|---|---|---|---|---|---|']
    for c in CATEGORIES:
        for x in cases:
            if x.get('category') != c or x.get('kind') == 'permitted':
                continue
            enforcement = '; '.join(
                f"{e.get('location')} ({', '.join(str(r) for r in _list(e.get('refs')))})"
                for e in _list(x.get('enforcement')) if isinstance(e, dict)) or '-'
            principal = _dict(x.get('principal'))
            who = f"`{principal.get('id')}`" + (' (root attempt)' if principal.get('root_attempt')
                                                else '')
            req = f" Requires {', '.join(str(r) for r in _list(x.get('requires')))}."                 if x.get('requires') else ''
            comp = f" Compensated by {_ids(x.get('compensated_by'))}." \
                if x.get('compensated_by') else ''
            out.append(
                f"| `{x.get('id')}` | {c} | {x.get('kind')} | {who} | "
                f"{_cell(_str(x.get('attempt')))}{req}{comp} | {_cell(probe_text(x.get('probe')))} | "
                f"{_cell(', '.join(str(o) for o in _list(_dict(x.get('expected')).get('outcomes'))))} | "
                f"{_cell(enforcement)} | `{x.get('positive_control')}` | {_ids(x.get('carried'))} |")
    out += ['', '### Positive controls', '',
            '| Control | Category | Attempt | Probe | Expected |', '|---|---|---|---|---|']
    for x in cases:
        if x.get('kind') == 'permitted':
            out.append(f"| `{x.get('id')}` | {x.get('category')} | {_cell(_str(x.get('attempt')))} | "
                       f"{_cell(probe_text(x.get('probe')))} | "
                       f"{_cell(', '.join(str(o) for o in _list(_dict(x.get('expected')).get('outcomes'))))} |")
    out += ['', '### Live sensitivity mutations (`containment-probe --sensitivity`)', '',
            '| Mutation | Case | Pointed at | Note |', '|---|---|---|---|']
    for m in _list(cat.get('mutations')):
        if isinstance(m, dict):
            out.append(f"| `{m.get('id')}` | `{m.get('case')}` | "
                       f"{_cell(probe_text({'source': 'containment-probe', 'op': m.get('op'), 'args': m.get('args')}))} | "
                       f"{_cell(_str(m.get('note')))} |")
    out.append('')
    return '\n'.join(out)


def summary(catalogue):
    cases = [x for x in _list(_dict(catalogue).get('cases')) if isinstance(x, dict)]
    kinds = {}
    for x in cases:
        kinds[x.get('kind')] = kinds.get(x.get('kind'), 0) + 1
    return (f"version {_dict(catalogue).get('version')}: {len(cases)} cases ("
            + ', '.join(f'{k} {v}' for k, v in sorted(kinds.items(), key=str)) +
            f") in {len({x.get('category') for x in cases})} categories; "
            f"{len(_list(_dict(catalogue).get('mutations')))} mutations")


def _load(root, rel):
    try:
        return json.loads((Path(root) / rel).read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        return {}


class Inputs:
    """The files a catalogue is checked against under a root, loaded once (the load/evaluate
    seam): each JSON file the catalogue names (properties, matrix, profile) is parsed on first
    use and kept, and the repository files the checks read go through one ``csi.RepoFiles``."""

    def __init__(self, root):
        self.root = root
        self.files = csi.RepoFiles(root)
        self._json = {}

    def json(self, rel):
        if rel not in self._json:
            self._json[rel] = _load(self.root, rel)
        return self._json[rel]


def load_inputs(root):
    """The inputs ``evaluate`` takes, under ROOT."""
    return Inputs(root)


def evaluate(catalogue, inventory, inputs, readme_text=None, properties=None, matrix=None,
             profile=None):
    """Return the problems found in ``catalogue`` (a parsed JSON value) with already-loaded
    INPUTS (``load_inputs``): the files it names are read through INPUTS, once for all
    evaluations, and none of them is changed."""
    cat = _dict(catalogue)
    if properties is None:
        properties = inputs.json(_str(cat.get('properties')) or PROPERTIES)
    if matrix is None:
        matrix = inputs.json(_str(cat.get('matrix')) or MATRIX)
    if profile is None:
        profile = inputs.json(_str(cat.get('profile')))
    return Checker(catalogue, inventory, inputs.root, readme_text, properties, matrix, profile,
                   files=inputs.files).run()


def check(catalogue, inventory, root, readme_text=None, properties=None, matrix=None,
          profile=None):
    """Return the problems found in ``catalogue`` (a parsed JSON value)."""
    return evaluate(catalogue, inventory, load_inputs(root), readme_text, properties, matrix, profile)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--root', default='.', help='repository root (default: .)')
    parser.add_argument('--catalogue', help='catalogue file (default: '
                        '<root>/security/containment-cases.json)')
    parser.add_argument('--inventory', help='security inventory (default: the catalogue\'s '
                        '"inventory" entry under the root)')
    parser.add_argument('--readme', help='README with the generated block (default: the '
                        'catalogue\'s "readme" entry under the root)')
    parser.add_argument('--list', action='store_true',
                        help='also print each case with its kind, category and control')
    parser.add_argument('--render', action='store_true',
                        help='print the README\'s generated block and exit')
    args = parser.parse_args(argv)
    root = Path(args.root)
    path = Path(args.catalogue) if args.catalogue else root / DEFAULT_CATALOGUE
    try:
        catalogue = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        print(f'ERROR: cannot read {path}: {exc}', file=sys.stderr)
        return 2
    if args.render:
        sys.stdout.write(render(catalogue))
        return 0
    inv_rel = catalogue.get('inventory') if isinstance(catalogue, dict) else None
    inv_path = Path(args.inventory) if args.inventory else root / (inv_rel or csi.DEFAULT_INVENTORY)
    try:
        inventory = json.loads(inv_path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        print(f'ERROR: cannot read {inv_path}: {exc}', file=sys.stderr)
        return 2
    if not isinstance(inventory, dict):
        print(f'ERROR: {inv_path} is not a JSON object', file=sys.stderr)
        return 2
    readme_rel = args.readme or (catalogue.get('readme') if isinstance(catalogue, dict) else None)
    readme_text = None
    if readme_rel:
        readme_path = Path(args.readme) if args.readme else root / readme_rel
        try:
            readme_text = readme_path.read_text(encoding='utf-8')
        except OSError as exc:
            print(f'ERROR: cannot read {readme_path}: {exc}', file=sys.stderr)
            return 2
    problems = check(catalogue, inventory, root, readme_text)
    if args.list and isinstance(catalogue, dict):
        for x in _list(catalogue.get('cases')):
            if isinstance(x, dict):
                print(f"{x.get('id')}: {x.get('category')} {x.get('kind')} "
                      f"(control {x.get('positive_control')})")
    for problem in problems:
        print(f'FAIL {problem}')
    if problems:
        print(f'FAIL {path.as_posix()}: {len(problems)} problem(s)')
        return 1
    print(f'PASS {path.as_posix()}: {summary(catalogue)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
