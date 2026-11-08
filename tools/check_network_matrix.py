"""Check the deny-by-default network matrix (plan leaf S-01.4).

``policy/network-matrix.json`` classifies every communication between the trust domains of
the security inventory (``security/inventory.json``, S-01.1): one or more rows for every
ordered pair of ``td-*`` ids (a domain with itself included), each with a verdict (allow,
deny or disclosed), its protocol and endpoint (an inventory asset or a profiles P7 endpoint
class), the credentials it uses, its enforcement points (prevention, detection or
disclosure; host, guest, container or Gitea), its status (observed, planned or decided) and
the inspection that shows it. ``external_edges`` add the paths between a domain and what
lies outside every domain (the LAN, the internet, a model provider). ``policy/README.md``
renders it. This checker enforces the leaf's acceptance mechanically: unexpected
management and credential access is denied, and every allowed path is named and enforced.

It fails when:

- an ordered domain pair has no row, a row cannot be classified (a missing or unknown
  verdict, status, protocol, endpoint or enforcement kind), or a row carries an unknown key;
- an ``allow`` from an untrusted or contained domain into a trusted one (or the trusted
  computing base) names no profiles P7 endpoint class (``management`` excluded), targets a
  management or credential asset, or uses a credential of privileged authority;
- an ``allow`` names no prevention mechanism, a ``disclosed`` row names no finding, or a
  ``deny`` names no enforcement;
- an id does not resolve: a domain, an asset, a credential, a finding, a plan leaf, a
  profile endpoint; or an inventory asset has no class, or a class contradicts the asset's
  kind or its privileged credentials;
- an ``observed`` row has no evidence, a ``planned`` row no plan leaf that will observe it
  (``verify_at``; ``builds_at`` alone is not enough), or a ``decided`` row no decision
  source and no plan leaf;
- an active profile's endpoint (``network.endpoints`` without a deferred status) or
  ``launch.argv`` forward does not appear as an ``allow`` row (a profile is active when its
  provider validation passed);
- an ``owner_act`` row is ``observed`` without a cited bootstrap-log approval that occurs in
  the log verbatim;
- an untrusted or contained domain has no external row;
- a machine path appears; or the README omits an edge id, or its generated tables differ
  from ``--render``.

It needs only the standard library and reads nothing outside the repository.

Usage (from the repository root):
    python -I -B tools/check_network_matrix.py [--matrix FILE] [--root DIR] [--list] [--render]

Exit status: 0 PASS, 1 FAIL, 2 could not run.
"""
import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    'check_security_inventory', Path(__file__).resolve().parent / 'check_security_inventory.py')
csi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(csi)

SCHEMA = 'ai-engineering-harness/policy/network-matrix/v1'
DEFAULT_MATRIX = Path('policy') / 'network-matrix.json'
PROPERTIES = Path('profiles') / 'properties.json'
BOOTSTRAP_LOG = 'evidence/bootstrap-log.md'

VERDICTS = ('allow', 'deny', 'disclosed')
STATUSES = ('observed', 'planned', 'decided')
ENFORCEMENT_KINDS = ('prevention', 'detection', 'disclosure')
ENFORCEMENT_WHERE = ('host', 'guest', 'container', 'gitea')
ASSET_CLASSES = ('management', 'credential', 'service', 'workload', 'store', 'host', 'endpoint',
                 'repository')
FORBIDDEN_CLASSES = ('management', 'credential')
TRUSTED = ('trusted', 'trusted-computing-base')
EXPOSED = ('untrusted', 'contained')
# asset kinds that fix (part of) the class: a secret or credential store is a credential
# asset; an API, a socket or a privileged unit is a management or credential asset
KIND_CLASSES = {'secret-file': ('credential',), 'credential-store': ('credential',),
                'api': FORBIDDEN_CLASSES, 'socket': FORBIDDEN_CLASSES,
                'privileged-unit': FORBIDDEN_CLASSES}

EDGE_ID = re.compile(r'^nm-[a-z0-9]+(-[a-z0-9]+)*$')
TOP_KEYS = {'schema', 'plan_leaf', 'title', 'as_of', 'baseline_commit', 'inventory', 'readme',
            'checker', 'decision', 'verdicts', 'statuses', 'externals', 'asset_classes', 'edges',
            'external_edges', 'sources', 'notes'}
EDGE_KEYS = {'id', 'name', 'from', 'to', 'verdict', 'protocol', 'endpoint', 'credentials',
             'enforcement', 'status', 'evidence', 'sources', 'builds_at', 'verify_at',
             'owner_act', 'owner_approval', 'findings', 'inspection', 'profile_endpoints',
             'notes'}
ENFORCEMENT_KEYS = {'mechanism', 'kind', 'where'}
APPROVAL_KEYS = {'link', 'quote'}

GENERATED_BEGIN = '<!-- BEGIN GENERATED: python -I -B tools/check_network_matrix.py --render -->'
GENERATED_END = '<!-- END GENERATED -->'


def _list(value):
    return value if isinstance(value, list) else []


def _dict(value):
    return value if isinstance(value, dict) else {}


def _str(value):
    return value if isinstance(value, str) else ''


def _in(key, table):
    return isinstance(key, str) and key in table


def profile_endpoint_keys(name, profile):
    """{key: (kind, active)} of one profile: '<name>:<class>:<host_port>' for every network
    endpoint (active unless its status says deferred) and '<name>:argv:<forward>' for every
    hostfwd or guestfwd rule of launch.argv."""
    out = {}
    for e in _list(_dict(profile.get('network')).get('endpoints')):
        if not isinstance(e, dict):
            continue
        deferred = _str(e.get('status')).startswith('deferred')
        out[f"{name}:{e.get('class')}:{e.get('host_port')}"] = ('endpoint', not deferred)
    argv = _list(_dict(profile.get('launch')).get('argv'))
    for i, arg in enumerate(argv):
        if arg == '-netdev' and i + 1 < len(argv):
            for part in str(argv[i + 1]).split(','):
                if part.startswith(('hostfwd=', 'guestfwd=')):
                    out[f'{name}:argv:{part}'] = ('forward', True)
    return out


def active_profile(profile):
    return _str(_dict(profile.get('status')).get('provider_validation')).startswith('PASS')


class Checker(csi.Checker):
    """Reuses the inventory checker's id tables, link and machine-path helpers."""

    def __init__(self, matrix, inventory, root, readme_text=None, properties=None, profiles=None):
        super().__init__(inventory, root, readme_text)
        self.matrix = matrix
        self.properties = properties if isinstance(properties, dict) else {}
        self.profiles = profiles if isinstance(profiles, dict) else {}

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
        m = self.matrix
        if not isinstance(m, dict):
            self.add('SCHEMA', 'matrix', 'the matrix must be a JSON object')
            return self.problems
        if m.get('schema') != SCHEMA:
            self.add('SCHEMA', 'schema', f'expected {SCHEMA!r}')
        self.keys('matrix', m, TOP_KEYS)
        if sorted(_dict(m.get('verdicts'))) != sorted(VERDICTS):
            self.add('SCHEMA', 'verdicts', f'must define exactly {list(VERDICTS)}')
        if sorted(_dict(m.get('statuses'))) != sorted(STATUSES):
            self.add('SCHEMA', 'statuses', f'must define exactly {list(STATUSES)}')
        for key in ('inventory', 'readme', 'checker', 'decision'):
            if key in m:
                self.check_link(key, m.get(key))
        if not self.check_links('matrix', m, 'sources'):
            self.add('STATUS_UNSUPPORTED', 'matrix.sources', 'the matrix needs source links')
        self.check_machine_paths(m, 'matrix')

        self.domains = self.index('trust_domains')
        self.assets = self.index('assets')
        self.credentials = self.index('credentials')
        self.findings = self.index('findings')
        self.plan = self.plan_ids() or set()
        self.classes = [str(c) for c in _list(self.properties.get('endpoint_classes'))]
        self.externals = self.check_externals()
        self.asset_class = self.check_asset_classes()
        self.endpoint_keys = {}
        for name, profile in sorted(self.profiles.items()):
            self.endpoint_keys.update(profile_endpoint_keys(name, profile))
        edges = _list(m.get('edges'))
        externals = _list(m.get('external_edges'))
        if not edges:
            self.add('SCHEMA', 'edges', 'must be a non-empty list')
        seen = {}
        for collection, rows, external in (('edges', edges, False),
                                           ('external_edges', externals, True)):
            for n, row in enumerate(rows):
                where = f'{collection}[{n}]'
                if not isinstance(row, dict):
                    self.add('SCHEMA', where, 'must be an object')
                    continue
                ident = row.get('id')
                if not isinstance(ident, str) or not EDGE_ID.match(ident):
                    self.add('ID_INVALID', where, f'id {ident!r} must be nm-<kebab-case>')
                else:
                    if ident in seen:
                        self.add('ID_DUPLICATE', where, f'id {ident!r} is also {seen[ident]}')
                    seen[ident] = where
                    where = f'{collection}.{ident}'
                self.check_row(where, row, external)
        self.check_completeness(edges, externals)
        self.check_profile_endpoints(edges + externals)
        self.check_matrix_readme(edges + externals)
        return self.problems

    def check_externals(self):
        names = _dict(self.matrix.get('externals'))
        for key, text in names.items():
            if not isinstance(key, str) or not csi.EXTERNAL.match(key) or \
                    not isinstance(text, str) or not text.strip():
                self.add('SCHEMA', f'externals.{key}', 'an external:<name> with a description')
        if not names:
            self.add('SCHEMA', 'externals', 'must name the outside endpoints (external:<name>)')
        return names

    def check_asset_classes(self):
        classes = _dict(self.matrix.get('asset_classes'))
        for aid, asset in self.assets.items():
            where = f'asset_classes.{aid}'
            cls = classes.get(aid)
            if cls is None:
                self.add('ASSET_UNCLASSIFIED', where, 'every inventory asset needs a class')
                continue
            if cls not in ASSET_CLASSES:
                self.add('SCHEMA', where, f'class {cls!r} is not one of {ASSET_CLASSES}')
                continue
            allowed = KIND_CLASSES.get(asset.get('kind'))
            if allowed and cls not in allowed:
                self.add('ASSET_CLASS', where, f"a {asset.get('kind')} asset is {allowed}, not {cls}")
            privileged = [c for c in _list(asset.get('credentials')) if _dict(
                self.credentials.get(c) if isinstance(c, str) else None).get('authority')
                in csi.PRIVILEGED_AUTHORITIES]
            if privileged and cls not in FORBIDDEN_CLASSES:
                self.add('ASSET_CLASS', where, f'it holds privileged credentials {privileged}, so '
                         f'it is a management or credential asset, not {cls}')
        for aid in classes:
            if not _in(aid, self.assets):
                self.add('DANGLING_REF', f'asset_classes.{aid}', 'no such inventory asset')
        return classes

    def side(self, where, row, key, external):
        value = row.get(key)
        if _in(value, self.domains):
            return value
        if external and _in(value, self.externals):
            return value
        self.add('DANGLING_REF', where, f'{key} {value!r} is not a trust domain'
                 + (' or a declared external' if external else ''))
        return None

    def check_row(self, where, row, external):
        self.keys(where, row, EDGE_KEYS)
        for key in ('name', 'protocol'):
            if not isinstance(row.get(key), str) or not row.get(key).strip():
                self.add('UNCLASSIFIED', where, f'{key} is required')
        src = self.side(where, row, 'from', external)
        dst = self.side(where, row, 'to', external)
        if external and src is not None and dst is not None and \
                (src in self.externals) == (dst in self.externals):
            self.add('SCHEMA', where, 'an external row joins one trust domain and one external')
        verdict, status = row.get('verdict'), row.get('status')
        if verdict not in VERDICTS:
            self.add('UNCLASSIFIED', where, f'verdict {verdict!r} is not one of {VERDICTS}')
        if status not in STATUSES:
            self.add('UNCLASSIFIED', where, f'status {status!r} is not one of {STATUSES}')
        endpoint = row.get('endpoint')
        is_class = _in(endpoint, self.classes)
        if not is_class and not _in(endpoint, self.assets) and \
                not (external and _in(endpoint, self.externals)):
            self.add('UNCLASSIFIED', where, f'endpoint {endpoint!r} is neither an inventory asset '
                     'nor a profiles P7 endpoint class')
        creds = self.strings(where, row, 'credentials')
        for cid in creds:
            if cid not in self.credentials:
                self.add('DANGLING_REF', where, f'credential {cid!r} does not exist')
        findings = self.strings(where, row, 'findings')
        for fid in findings:
            if fid not in self.findings:
                self.add('DANGLING_REF', where, f'finding {fid!r} does not exist')
        enforcement = self.check_enforcement(where, row)
        for key in ('builds_at', 'verify_at'):
            leaf = row.get(key)
            if leaf is not None and not self.leaf_ok(leaf):
                self.add('DANGLING_REF', where, f'{key} {leaf!r} is not a plan leaf')
        evidence = self.check_links(where, row, 'evidence')
        sources = self.check_links(where, row, 'sources')
        if not isinstance(row.get('owner_act'), bool):
            self.add('SCHEMA', where, 'owner_act must be true or false')
        inspection = self.strings(where, row, 'inspection')
        for ref in self.strings(where, row, 'profile_endpoints'):
            if ref not in self.endpoint_keys:
                self.add('DANGLING_REF', where, f'profile endpoint {ref!r} is not in a profile')

        # verdict rules
        prevention = [e for e in enforcement if e.get('kind') == 'prevention']
        if verdict == 'allow' and not prevention:
            self.add('ALLOW_UNENFORCED', where, 'an allow names at least one prevention mechanism')
        if verdict == 'disclosed' and not findings:
            self.add('DISCLOSED_UNSUPPORTED', where, 'a disclosed path carries a finding')
        if verdict == 'deny' and not enforcement:
            self.add('DENY_UNENFORCED', where, 'a deny names its enforcement')
        if verdict == 'allow' and src in self.domains and dst in self.domains:
            self.check_trust_boundary(where, row, src, dst, endpoint, is_class, creds)
        # status rules
        if status == 'observed':
            if not evidence:
                self.add('STATUS_UNSUPPORTED', where, 'observed needs at least one evidence link')
            if not inspection:
                self.add('STATUS_UNSUPPORTED', where, 'observed needs an inspection command')
        elif status == 'planned' and not row.get('verify_at'):
            self.add('STATUS_UNSUPPORTED', where, 'planned needs the plan leaf that will observe '
                     'it (verify_at)')
        elif status == 'decided':
            if not any(str(s).startswith('decisions/') for s in sources):
                self.add('STATUS_UNSUPPORTED', where, 'decided needs a decision among its sources')
            if not row.get('builds_at'):
                self.add('STATUS_UNSUPPORTED', where, 'decided needs the leaf that builds it')
        if row.get('owner_act') is True and status == 'observed':
            self.check_owner_approval(where, row.get('owner_approval'))
        elif 'owner_approval' in row and row.get('owner_act') is not True:
            self.add('SCHEMA', where, 'owner_approval belongs to an owner_act row')

    def leaf_ok(self, leaf):
        if not isinstance(leaf, str) or not csi.PLAN_ID.match(leaf):
            return False
        if leaf.endswith('.x'):
            return any(i.startswith(leaf[:-1]) for i in self.plan)
        return leaf in self.plan

    def check_enforcement(self, where, row):
        out = []
        value = row.get('enforcement')
        if not isinstance(value, list):
            self.add('UNCLASSIFIED', where, 'enforcement must be a list')
            return out
        for n, e in enumerate(value):
            w = f'{where}.enforcement[{n}]'
            if not isinstance(e, dict):
                self.add('UNCLASSIFIED', w, 'must be an object')
                continue
            self.keys(w, e, ENFORCEMENT_KEYS)
            if not isinstance(e.get('mechanism'), str) or not e.get('mechanism').strip():
                self.add('UNCLASSIFIED', w, 'mechanism is required')
            if e.get('kind') not in ENFORCEMENT_KINDS:
                self.add('UNCLASSIFIED', w, f'kind must be one of {ENFORCEMENT_KINDS}')
            if e.get('where') not in ENFORCEMENT_WHERE:
                self.add('UNCLASSIFIED', w, f'where must be one of {ENFORCEMENT_WHERE}')
            out.append(e)
        return out

    def check_trust_boundary(self, where, row, src, dst, endpoint, is_class, creds):
        src_trust = self.domains[src].get('trust')
        dst_trust = self.domains[dst].get('trust')
        if src_trust not in EXPOSED or dst_trust not in TRUSTED:
            return
        if not is_class or endpoint == 'management':
            self.add('TRUST_BOUNDARY', where, f'an allow from {src} ({src_trust}) into {dst} '
                     f'({dst_trust}) names a profiles P7 endpoint class other than management, '
                     f'not {endpoint!r}')
        if self.asset_class.get(endpoint) in FORBIDDEN_CLASSES:
            self.add('TRUST_BOUNDARY', where, f'an allow from {src} into {dst} targets the '
                     f'{self.asset_class.get(endpoint)} asset {endpoint}')
        privileged = [c for c in creds if _dict(self.credentials.get(c)).get('authority')
                      in csi.PRIVILEGED_AUTHORITIES]
        if privileged:
            self.add('TRUST_BOUNDARY', where, f'an allow from {src} into {dst} uses privileged '
                     f'credentials {privileged}')

    def check_owner_approval(self, where, approval):
        if not isinstance(approval, dict) or set(approval) != APPROVAL_KEYS or \
                approval.get('link') != BOOTSTRAP_LOG or not isinstance(approval.get('quote'), str) \
                or len(approval.get('quote').strip()) < 12:
            self.add('OWNER_APPROVAL', where, f'an observed Owner act cites its approval: '
                     f'{{link: {BOOTSTRAP_LOG}, quote: <the approval, verbatim>}}')
            return
        text = self.read_text(BOOTSTRAP_LOG)
        if text is None or approval['quote'] not in text:
            self.add('OWNER_APPROVAL', where, f'the quoted approval is not in {BOOTSTRAP_LOG}')

    def check_completeness(self, edges, externals):
        pairs = {(r.get('from'), r.get('to')) for r in edges if isinstance(r, dict) and
                 isinstance(r.get('from'), str) and isinstance(r.get('to'), str)}
        for a in self.domains:
            for b in self.domains:
                if (a, b) not in pairs:
                    self.add('PAIR_MISSING', f'{a} -> {b}', 'every ordered pair of trust domains '
                             'needs a row; an unclassifiable pair is a failure, never an omission')
        sides = {r.get('from') for r in externals if isinstance(r, dict) and
                 isinstance(r.get('from'), str)}
        for did, d in self.domains.items():
            if d.get('trust') in EXPOSED and did not in sides:
                self.add('PAIR_MISSING', f'{did} -> external', f'an {d.get("trust")} domain needs '
                         'a row for its paths out of every domain (external_edges)')

    def check_profile_endpoints(self, rows):
        allowed = set()
        for r in rows:
            if isinstance(r, dict) and r.get('verdict') == 'allow':
                allowed.update(x for x in _list(r.get('profile_endpoints')) if isinstance(x, str))
        for name, profile in sorted(self.profiles.items()):
            if not active_profile(profile):
                continue
            for key, (kind, active) in sorted(profile_endpoint_keys(name, profile).items()):
                if active and key not in allowed:
                    self.add('PROFILE_ENDPOINT', key, f'an active {kind} of profile {name} '
                             'appears in no allow row')

    def check_matrix_readme(self, rows):
        if self.readme is None:
            return
        if csi.MACHINE_PATH.search(self.readme):
            self.add('MACHINE_PATH', 'readme', 'a machine-specific path must not be published')
        for r in rows:
            ident = r.get('id') if isinstance(r, dict) else None
            if isinstance(ident, str) and f'`{ident}`' not in self.readme:
                self.add('README_MISSING', ident, 'the README does not name this edge (as `id`)')
        block = generated_block(self.readme)
        if block is None:
            self.add('README_STALE', 'readme', 'the generated tables are missing their markers')
        elif block.strip() != render(self.matrix, self.inv).strip():
            self.add('README_STALE', 'readme', 'the generated tables differ from --render; '
                     're-render them from the matrix')


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


def _short(domain):
    return str(domain).replace('td-', '')


def render(matrix, inventory):
    """The README's generated tables, rendered from the matrix and the inventory."""
    matrix, inventory = _dict(matrix), _dict(inventory)
    rows = [r for r in _list(matrix.get('edges')) if isinstance(r, dict)]
    ext = [r for r in _list(matrix.get('external_edges')) if isinstance(r, dict)]
    domains = [d.get('id') for d in _list(inventory.get('trust_domains')) if isinstance(d, dict)]
    out = ['', '### Domain pairs', '',
           'Each cell lists the verdicts of the rows from the row domain to the column domain '
           '(A allow, D deny, X disclosed; lower case: planned or decided).', '',
           '| From \\ To | ' + ' | '.join(_short(d) for d in domains) + ' |',
           '|---|' + '---|' * len(domains)]
    for a in domains:
        cells = []
        for b in domains:
            marks = []
            for r in rows:
                if r.get('from') == a and r.get('to') == b:
                    m = {'allow': 'A', 'deny': 'D', 'disclosed': 'X'}.get(_str(r.get('verdict')), '?')
                    marks.append(m if r.get('status') == 'observed' else m.lower())
            cells.append(''.join(marks) or '**missing**')
        out.append(f'| {_short(a)} | ' + ' | '.join(cells) + ' |')

    def table(title, entries):
        lines = ['', f'### {title}', '',
                 '| Edge | From | To | Verdict | Protocol | Endpoint | Credentials | '
                 'Enforcement | Status | Leaf | Owner act | Inspection |',
                 '|---|---|---|---|---|---|---|---|---|---|---|---|']
        for r in entries:
            enforcement = '; '.join(f"{_cell(_str(e.get('mechanism')))} ({e.get('kind')}, "
                                    f"{e.get('where')})" for e in _list(r.get('enforcement'))
                                    if isinstance(e, dict)) or '-'
            leaves = ', '.join(f'{k.split("_")[0]} {_cell(r.get(k))}' for k in ('builds_at', 'verify_at')
                               if r.get(k)) or '-'
            note = ''
            if _list(r.get('findings')):
                note = f" Findings: {_ids(r.get('findings'))}."
            lines.append(
                f"| `{r.get('id')}` {_cell(_str(r.get('name')))}{note} | `{r.get('from')}` | "
                f"`{r.get('to')}` | {r.get('verdict')} | {_cell(_str(r.get('protocol')))} | "
                f"`{r.get('endpoint')}` | {_ids(r.get('credentials'))} | {enforcement} | "
                f"{r.get('status')} | {leaves} | {'yes' if r.get('owner_act') is True else 'no'} | "
                f"{_cell('; '.join(str(x) for x in _list(r.get('inspection')))) or '-'} |")
        return lines
    out += table('Edges between trust domains', rows)
    out += table('Edges to and from outside every domain', ext)
    out.append('')
    return '\n'.join(out)


def summary(matrix):
    rows = [r for r in _list(_dict(matrix).get('edges')) + _list(_dict(matrix).get('external_edges'))
            if isinstance(r, dict)]
    count = {}
    for key in ('verdict', 'status'):
        for r in rows:
            value = r.get(key) if isinstance(r.get(key), str) else repr(r.get(key))
            count.setdefault(key, {}).setdefault(value, 0)
            count[key][value] += 1
    fmt = lambda d: ', '.join(f'{k} {v}' for k, v in sorted(d.items(), key=str))
    return (f"{len(_list(_dict(matrix).get('edges')))} domain edges and "
            f"{len(_list(_dict(matrix).get('external_edges')))} external edges; verdicts: "
            f"{fmt(count.get('verdict', {}))}; statuses: {fmt(count.get('status', {}))}; "
            f"Owner acts: {sum(1 for r in rows if r.get('owner_act') is True)}")


def load_profiles(root):
    out = {}
    for path in sorted((Path(root) / 'profiles').glob('*/profile.json')):
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get('name'), str):
            out[data['name']] = data
    return out


def check(matrix, inventory, root, readme_text=None, properties=None, profiles=None):
    """Return the problems found in ``matrix`` against ``inventory`` (parsed JSON values)."""
    if properties is None:
        try:
            properties = json.loads((Path(root) / PROPERTIES).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            properties = {}
    if profiles is None:
        profiles = load_profiles(root)
    return Checker(matrix, inventory, root, readme_text, properties, profiles).run()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--root', default='.', help='repository root (default: .)')
    parser.add_argument('--matrix', help='matrix file (default: <root>/policy/network-matrix.json)')
    parser.add_argument('--inventory', help='security inventory (default: the matrix\'s '
                        '"inventory" entry under the root)')
    parser.add_argument('--readme', help='README naming every edge (default: the matrix\'s '
                        '"readme" entry under the root)')
    parser.add_argument('--list', action='store_true',
                        help='also print each edge with its verdict and status')
    parser.add_argument('--render', action='store_true',
                        help='print the README\'s generated tables and exit')
    args = parser.parse_args(argv)
    root = Path(args.root)
    path = Path(args.matrix) if args.matrix else root / DEFAULT_MATRIX
    try:
        matrix = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        print(f'ERROR: cannot read {path}: {exc}', file=sys.stderr)
        return 2
    inv_rel = matrix.get('inventory') if isinstance(matrix, dict) else None
    inv_path = Path(args.inventory) if args.inventory else root / (inv_rel or csi.DEFAULT_INVENTORY)
    try:
        inventory = json.loads(inv_path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        print(f'ERROR: cannot read {inv_path}: {exc}', file=sys.stderr)
        return 2
    if not isinstance(inventory, dict):
        print(f'ERROR: {inv_path} is not a JSON object', file=sys.stderr)
        return 2
    if args.render:
        sys.stdout.write(render(matrix, inventory))
        return 0
    readme_rel = args.readme or (matrix.get('readme') if isinstance(matrix, dict) else None)
    readme_text = None
    if readme_rel:
        readme_path = Path(args.readme) if args.readme else root / readme_rel
        try:
            readme_text = readme_path.read_text(encoding='utf-8')
        except OSError as exc:
            print(f'ERROR: cannot read {readme_path}: {exc}', file=sys.stderr)
            return 2
    problems = check(matrix, inventory, root, readme_text)
    if args.list and isinstance(matrix, dict):
        for r in _list(matrix.get('edges')) + _list(matrix.get('external_edges')):
            if isinstance(r, dict):
                flag = ' [Owner act]' if r.get('owner_act') is True else ''
                print(f"{r.get('id')}: {r.get('from')} -> {r.get('to')} {r.get('verdict')} "
                      f"({r.get('status')}){flag}")
    for problem in problems:
        print(f'FAIL {problem}')
    if problems:
        print(f'FAIL {path.as_posix()}: {len(problems)} problem(s)')
        return 1
    print(f'PASS {path.as_posix()}: {summary(matrix)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
