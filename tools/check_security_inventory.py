"""Check the security inventory (plan leaf S-01.1).

``security/inventory.json`` lists the trust domains, principals, credentials, protected
assets and privileged operations of the harness, with every entry marked planned,
observed, unknown or conflict. ``security/README.md`` is its human-readable record.
This checker enforces the leaf's acceptance mechanically:

- every privileged operation names exactly one principal, and that principal exists; a
  performer it names (``observed_performer``, ``planned_performer``) is a principal too;
- no credential that an agent principal holds, manages or may read carries a
  privileged authority class (Owner, admin, executor or management), and no
  Owner-only operation uses a credential that an agent principal holds, manages or may
  read; an Owner-only operation's principal holds Owner authority, and no agent
  principal is described as holding Owner authority;
- a privileged credential that an agent principal can reach because it shares an OS
  identity with the holder carries a finding that names that agent principal
  (decision 0004, Owner clarification 5: such agents are not isolated principals);
- every referenced principal, credential, asset, trust domain, finding and plan leaf
  exists;
- every entry carries a status from the closed set: ``observed`` needs evidence links,
  ``planned`` needs source links, ``unknown`` and ``conflict`` need a finding; every
  link resolves to a file in the repository, and a blueprint anchor or plan id to an
  element of it;
- no machine path appears in the inventory, and every operation and finding id is
  named in the README.

It needs only the standard library and reads nothing outside the repository.

Usage (from the repository root):
    python -I -B tools/check_security_inventory.py [--inventory FILE] [--root DIR] [--list]

Exit status: 0 PASS, 1 FAIL, 2 could not run.
"""
import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

SCHEMA = 'ai-engineering-harness/security/inventory/v1'
DEFAULT_INVENTORY = Path('security') / 'inventory.json'
PLAN = 'AI_Engineering_Implementation_Project_Plan_Overseer_Prompts_2026-10-31.json'

STATUSES = ('planned', 'observed', 'unknown', 'conflict')
TRUST_LEVELS = ('trusted', 'trusted-computing-base', 'contained', 'untrusted')
PRINCIPAL_KINDS = ('owner', 'owner-host-account', 'trusted-service', 'executor',
                   'git-admin', 'agent', 'ci-job', 'guest-system', 'operator-login')
AGENT_KINDS = ('agent', 'ci-job')
OWNER_KINDS = ('owner', 'owner-host-account')
AUTHORITIES = ('owner', 'admin', 'executor', 'management', 'scoped', 'guest-local',
               'provider')
PRIVILEGED_AUTHORITIES = ('owner', 'admin', 'executor', 'management')
ASSET_KINDS = ('host', 'guest', 'process', 'container', 'directory', 'secret-file',
               'socket', 'listener', 'api', 'store', 'repository', 'service',
               'credential-store', 'privileged-unit')
FINDING_KINDS = ('unknown', 'conflict', 'open-risk', 'limit')
COLLECTIONS = ('trust_domains', 'principals', 'credentials', 'assets', 'operations',
               'findings')

ID = re.compile(r'^[a-z][a-z0-9]*(-[a-z0-9]+)*$')
PLAN_ID = re.compile(r'^[A-Z]-[0-9]{2}(\.[0-9]+)*(\.x)?$')
EXTERNAL = re.compile(r'^external:[a-z0-9][a-z0-9.-]*$')
# A machine path: a Windows drive path, a UNC path or a user-profile variable.
MACHINE_PATH = re.compile(r'(?<![A-Za-z0-9])[A-Za-z]:[\\/]|\\\\[A-Za-z0-9]|%USERPROFILE%',
                          re.IGNORECASE)


@dataclass(frozen=True)
class Problem:
    code: str
    where: str
    message: str

    def __str__(self):
        return f'{self.code}: {self.where}: {self.message}'


class RepoFiles:
    """The repository files a checker reads under ROOT, read only: each text read once, each
    file tested once and the plan's ids parsed once. A checker makes its own by default; a
    caller that checks many inputs against one unchanged tree may load one and share it (the
    checkers' load/evaluate seam)."""

    def __init__(self, root):
        self.root = Path(root)
        self._text = {}
        self._is_file = {}
        self._plan_ids = {}

    def read_text(self, rel):
        if rel not in self._text:
            try:
                self._text[rel] = (self.root / rel).read_text(encoding='utf-8')
            except (OSError, UnicodeDecodeError):
                self._text[rel] = None
        return self._text[rel]

    def is_file(self, rel):
        if rel not in self._is_file:
            self._is_file[rel] = (self.root / rel).is_file()
        return self._is_file[rel]

    def plan_ids(self):
        if 'ids' not in self._plan_ids:
            self._plan_ids['ids'] = _plan_ids(self.read_text(PLAN))
        ids = self._plan_ids['ids']
        return None if ids is None else set(ids)


def _plan_ids(text):
    if text is None:
        return None
    try:
        plan = json.loads(text)
    except ValueError:
        return None
    ids = {w.get('id') for w in plan.get('work_packages', []) if isinstance(w, dict)}
    parents = plan.get('decomposition', {}).get('parent_outcomes', [])
    ids |= {p.get('id') for p in parents if isinstance(p, dict)}
    return frozenset(i for i in ids if isinstance(i, str))


class Checker:
    def __init__(self, inventory, root, readme_text=None, files=None):
        self.inv = inventory
        self.root = Path(root)
        self.readme = readme_text
        self.problems = []
        self.files = files if files is not None else RepoFiles(root)

    def add(self, code, where, message):
        self.problems.append(Problem(code, where, message))

    # -- helpers -----------------------------------------------------------------

    def items(self, name):
        value = self.inv.get(name)
        return value if isinstance(value, list) else []

    def index(self, name):
        return {e['id']: e for e in self.items(name)
                if isinstance(e, dict) and isinstance(e.get('id'), str)}

    def read_text(self, rel):
        return self.files.read_text(rel)

    def plan_ids(self):
        return self.files.plan_ids()

    def check_link(self, where, link):
        """A link is a repository-relative file path, optionally with #anchor."""
        if not isinstance(link, str) or not link:
            self.add('LINK_INVALID', where, f'not a link: {link!r}')
            return
        path, _, anchor = link.partition('#')
        rel = Path(path)
        if rel.is_absolute() or path.startswith(('/', '\\')) or '..' in rel.parts \
                or MACHINE_PATH.search(path):
            self.add('LINK_INVALID', where, f'not a repository-relative path: {link}')
            return
        if not self.files.is_file(rel):
            self.add('LINK_MISSING', where, f'no such file in the repository: {path}')
            return
        if not anchor:
            return
        suffix = rel.suffix.lower()
        if suffix in ('.html', '.htm'):
            text = self.read_text(path) or ''
            if f'id="{anchor}"' not in text:
                self.add('ANCHOR_MISSING', where, f'{path} has no element id {anchor!r}')
        elif path == PLAN:
            ids = self.plan_ids() or set()
            if anchor not in ids:
                self.add('ANCHOR_MISSING', where, f'the plan has no work package {anchor!r}')

    def check_links(self, where, entry, key):
        links = entry.get(key, [])
        if not isinstance(links, list):
            self.add('LINK_INVALID', where, f'{key} must be a list')
            return []
        for link in links:
            self.check_link(f'{where}.{key}', link)
        return links

    def check_status(self, where, entry, findings):
        status = entry.get('status')
        if status not in STATUSES:
            self.add('STATUS_INVALID', where, f'status {status!r} is not one of {STATUSES}')
            return
        sources = self.check_links(where, entry, 'sources')
        evidence = self.check_links(where, entry, 'evidence')
        refs = entry.get('findings', [])
        if not isinstance(refs, list):
            self.add('REF_INVALID', where, 'findings must be a list')
            refs = []
        for ref in refs:
            if ref not in findings:
                self.add('DANGLING_REF', where, f'finding {ref!r} does not exist')
        if status == 'observed' and not evidence:
            self.add('STATUS_UNSUPPORTED', where, 'observed needs at least one evidence link')
        elif status == 'planned' and not sources:
            self.add('STATUS_UNSUPPORTED', where, 'planned needs at least one source link')
        elif status in ('unknown', 'conflict') and not refs:
            self.add('STATUS_UNSUPPORTED', where, f'{status} needs at least one finding')
        if status == 'conflict':
            kinds = {findings[r].get('kind') for r in refs if r in findings}
            if 'conflict' not in kinds:
                self.add('STATUS_UNSUPPORTED', where, 'conflict needs a finding of kind conflict')

    def ref(self, where, value, table, what, allow_external=False, allow_null=False):
        if value is None and allow_null:
            return None
        if allow_external and isinstance(value, str) and EXTERNAL.match(value):
            return None
        if not isinstance(value, str) or value not in table:
            self.add('DANGLING_REF', where, f'{what} {value!r} does not exist')
            return None
        return table[value]

    # -- the checks --------------------------------------------------------------

    def run(self):
        inv = self.inv
        if not isinstance(inv, dict):
            self.add('SCHEMA', 'inventory', 'the inventory must be a JSON object')
            return self.problems
        if inv.get('schema') != SCHEMA:
            self.add('SCHEMA', 'schema', f'expected {SCHEMA!r}')
        for name in COLLECTIONS:
            if not isinstance(inv.get(name), list) or not inv.get(name):
                self.add('SCHEMA', name, 'must be a non-empty list')
        if list(inv.get('privileged_authority_classes', [])) != list(PRIVILEGED_AUTHORITIES):
            self.add('SCHEMA', 'privileged_authority_classes',
                     f'must be exactly {list(PRIVILEGED_AUTHORITIES)}')
        if sorted(inv.get('statuses', {})) != sorted(STATUSES):
            self.add('SCHEMA', 'statuses', f'must define exactly {list(STATUSES)}')
        for link in inv.get('privileged_authority_basis', []):
            self.check_link('privileged_authority_basis', link)

        self.check_ids()
        self.check_machine_paths(inv, 'inventory')
        domains = self.index('trust_domains')
        principals = self.index('principals')
        credentials = self.index('credentials')
        assets = self.index('assets')
        findings = self.index('findings')
        everything = {**domains, **principals, **credentials, **assets,
                      **self.index('operations'), **findings}

        self.check_findings(findings, everything)
        for d in self.items('trust_domains'):
            where = f"trust_domains.{d.get('id')}"
            if d.get('trust') not in TRUST_LEVELS:
                self.add('SCHEMA', where, f"trust {d.get('trust')!r} is not one of {TRUST_LEVELS}")
            self.check_status(where, d, findings)
        self.check_principals(principals, domains, findings)
        self.check_credentials(credentials, principals, findings)
        self.check_assets(assets, principals, credentials, findings)
        self.check_operations(principals, credentials, assets, findings)
        self.check_readme()
        return self.problems

    def check_ids(self):
        seen = {}
        for name in COLLECTIONS:
            for n, entry in enumerate(self.items(name)):
                where = f'{name}[{n}]'
                if not isinstance(entry, dict):
                    self.add('SCHEMA', where, 'must be an object')
                    continue
                ident = entry.get('id')
                if not isinstance(ident, str) or not ID.match(ident):
                    self.add('ID_INVALID', where, f'id {ident!r} must be lower-case kebab-case')
                    continue
                if ident in seen:
                    self.add('ID_DUPLICATE', where, f'id {ident!r} is also used in {seen[ident]}')
                seen[ident] = name

    def check_machine_paths(self, value, where):
        if isinstance(value, str):
            if MACHINE_PATH.search(value):
                self.add('MACHINE_PATH', where, 'a machine-specific path must not be published; '
                         'describe the location generically')
        elif isinstance(value, dict):
            for key, item in value.items():
                self.check_machine_paths(item, f'{where}.{key}')
        elif isinstance(value, list):
            for n, item in enumerate(value):
                self.check_machine_paths(item, f'{where}[{n}]')

    def check_findings(self, findings, everything):
        plan_ids = self.plan_ids()
        if plan_ids is None:
            self.add('LINK_MISSING', 'findings', f'cannot read the plan {PLAN}')
            plan_ids = set()
        for fid, f in findings.items():
            where = f'findings.{fid}'
            if f.get('kind') not in FINDING_KINDS:
                self.add('SCHEMA', where, f"kind {f.get('kind')!r} is not one of {FINDING_KINDS}")
            for key in ('title', 'detail'):
                if not isinstance(f.get(key), str) or not f.get(key).strip():
                    self.add('SCHEMA', where, f'{key} is required')
            refs = f.get('refs', [])
            if not isinstance(refs, list) or not refs:
                self.add('SCHEMA', where, 'refs must name at least one entry')
                refs = []
            for ref in refs:
                if ref not in everything:
                    self.add('DANGLING_REF', where, f'ref {ref!r} does not exist')
            if not self.check_links(where, f, 'citations'):
                self.add('STATUS_UNSUPPORTED', where, 'a finding needs at least one citation')
            for leaf in f.get('carried_to', []):
                if not isinstance(leaf, str) or not PLAN_ID.match(leaf):
                    self.add('DANGLING_REF', where, f'carried_to {leaf!r} is not a plan id')
                    continue
                if leaf.endswith('.x'):
                    prefix = leaf[:-1]
                    if not any(i.startswith(prefix) for i in plan_ids):
                        self.add('DANGLING_REF', where, f'no plan leaf under {leaf!r}')
                elif leaf not in plan_ids:
                    self.add('DANGLING_REF', where, f'plan leaf {leaf!r} does not exist')

    def check_principals(self, principals, domains, findings):
        for pid, p in principals.items():
            where = f'principals.{pid}'
            kind = p.get('kind')
            if kind not in PRINCIPAL_KINDS:
                self.add('SCHEMA', where, f'kind {kind!r} is not one of {PRINCIPAL_KINDS}')
            for key in ('agent_controlled', 'owner_authority', 'independently_isolated'):
                if not isinstance(p.get(key), bool):
                    self.add('SCHEMA', where, f'{key} must be true or false')
            if p.get('domain') is None:
                if p.get('status') not in ('unknown', 'conflict'):
                    self.add('DANGLING_REF', where,
                             'a principal without a trust domain must be unknown or conflict')
            else:
                self.ref(where, p.get('domain'), domains, 'trust domain')
            if kind in AGENT_KINDS and p.get('agent_controlled') is not True:
                self.add('AGENT_KIND', where, f'a {kind} principal is agent-controlled')
            if kind in OWNER_KINDS and p.get('agent_controlled') is not False:
                self.add('AGENT_KIND', where, f'a {kind} principal is not agent-controlled')
            if p.get('owner_authority') is True and (p.get('agent_controlled') is not False
                                                     or kind not in OWNER_KINDS):
                self.add('AGENT_OWNER_AUTHORITY', where,
                         'only the Owner and the Owner\'s own host account hold Owner authority, '
                         'never an agent-controlled principal')
            identity = p.get('identity')
            if not isinstance(identity, dict) or not isinstance(identity.get('planned'), str) \
                    or not identity.get('planned').strip():
                self.add('SCHEMA', where, 'identity.planned is required')
                identity = {}
            observed = identity.get('observed')
            if observed is not None and (not isinstance(observed, str) or not observed.strip()):
                self.add('SCHEMA', where, 'identity.observed must be a description or null')
            if p.get('status') == 'observed' and observed is None:
                self.add('STATUS_UNSUPPORTED', where, 'an observed principal needs identity.observed')
            if observed is not None and not p.get('evidence'):
                self.add('STATUS_UNSUPPORTED', where,
                         'identity.observed needs at least one evidence link')
            shared = p.get('shares_os_identity_with')
            if shared is not None:
                other = self.ref(where, shared, principals, 'principal')
                if other is not None and other.get('owner_authority') is True:
                    if p.get('independently_isolated') is not False:
                        self.add('SHARED_IDENTITY_ISOLATED', where,
                                 f'shares the OS identity of {shared}, so it is not an '
                                 'independently isolated principal')
                    if not p.get('findings'):
                        self.add('SHARED_IDENTITY_UNDISCLOSED', where,
                                 f'shares the OS identity of {shared} without a finding')
            self.check_status(where, p, findings)

    def agent(self, principals, pid):
        p = principals.get(pid)
        return p is not None and p.get('agent_controlled') is True

    def custody(self, cred):
        """The principals a credential is designated to: holder, manager, readers."""
        readers = cred.get('readable_by', [])
        return [cred.get('holder'), cred.get('manager'),
                *(readers if isinstance(readers, list) else [])]

    def check_credentials(self, credentials, principals, findings):
        for cid, c in credentials.items():
            where = f'credentials.{cid}'
            authority = c.get('authority')
            if authority not in AUTHORITIES:
                self.add('SCHEMA', where, f'authority {authority!r} is not one of {AUTHORITIES}')
            for key in ('storage', 'scope', 'lifetime'):
                if not isinstance(c.get(key), str) or not c.get(key).strip():
                    self.add('SCHEMA', where, f'{key} is required')
            self.ref(where, c.get('issuer'), principals, 'issuer', allow_external=True)
            holder = self.ref(where, c.get('holder'), principals, 'holder')
            self.ref(where, c.get('manager'), principals, 'manager')
            if not isinstance(c.get('readable_by'), list):
                self.add('SCHEMA', where, 'readable_by must be a list')
            for reader in c.get('readable_by', []) if isinstance(c.get('readable_by'), list) else []:
                self.ref(where, reader, principals, 'reader')
            rotation = c.get('rotation_revocation_owner')
            if rotation is None:
                if not c.get('findings'):
                    self.add('STATUS_UNSUPPORTED', where,
                             'an undecided rotation and revocation owner needs a finding')
            else:
                self.ref(where, rotation, principals, 'rotation and revocation owner')
            agents = [pid for pid in self.custody(c) if self.agent(principals, pid)]
            if authority in PRIVILEGED_AUTHORITIES and agents:
                self.add('AGENT_PRIVILEGED_CREDENTIAL', where,
                         f'{authority} authority is held, managed or readable by agent '
                         f'principal(s) {sorted(set(agents))}')
            if authority == 'owner' and holder is not None and holder.get('owner_authority') is not True:
                self.add('AGENT_OWNER_AUTHORITY', where,
                         f'an Owner-authority credential held by {c.get("holder")}, '
                         'which holds no Owner authority')
            if authority in PRIVILEGED_AUTHORITIES:
                self.check_shared_reach(where, c, principals, findings)
            self.check_status(where, c, findings)

    def check_shared_reach(self, where, cred, principals, findings):
        """An agent sharing the OS identity of a custodian must be disclosed."""
        custodians = {pid for pid in self.custody(cred) if pid in principals}
        named = set()
        for ref in cred.get('findings', []):
            if ref in findings:
                named.update(findings[ref].get('refs', []))
        for pid, p in principals.items():
            if p.get('agent_controlled') is True and p.get('shares_os_identity_with') in custodians \
                    and pid not in named:
                self.add('SHARED_IDENTITY_UNDISCLOSED', where,
                         f'agent principal {pid} shares the OS identity of '
                         f"{p.get('shares_os_identity_with')}, which holds this credential; "
                         'it needs a finding that names it')

    def check_assets(self, assets, principals, credentials, findings):
        for aid, a in assets.items():
            where = f'assets.{aid}'
            if a.get('kind') not in ASSET_KINDS:
                self.add('SCHEMA', where, f"kind {a.get('kind')!r} is not one of {ASSET_KINDS}")
            if not isinstance(a.get('location'), str) or not a.get('location').strip():
                self.add('SCHEMA', where, 'location is required')
            self.ref(where, a.get('custodian'), principals, 'custodian')
            for cid in a.get('credentials', []):
                self.ref(where, cid, credentials, 'credential')
            self.check_status(where, a, findings)

    def check_operations(self, principals, credentials, assets, findings):
        for n, o in enumerate(self.items('operations')):
            if not isinstance(o, dict):
                continue
            where = f"operations.{o.get('id', n)}"
            if o.get('privileged') is False:
                self.add('SCHEMA', where, 'the inventory lists privileged operations only')
            if not isinstance(o.get('mechanism'), str) or not o.get('mechanism').strip():
                self.add('SCHEMA', where, 'mechanism is required')
            pid = o.get('principal')
            if 'principals' in o or not isinstance(pid, str):
                self.add('PRINCIPAL_NOT_ONE', where,
                         'a privileged operation names exactly one principal')
                principal = None
            else:
                principal = self.ref(where, pid, principals, 'principal')
            if 'observed_performer' in o:
                self.ref(where, o.get('observed_performer'), principals, 'observed performer')
            if 'planned_performer' in o:
                self.ref(where, o.get('planned_performer'), principals, 'planned performer')
            owner_only = o.get('owner_only')
            if not isinstance(owner_only, bool):
                self.add('SCHEMA', where, 'owner_only must be true or false')
            used = o.get('credentials', [])
            if not isinstance(used, list):
                self.add('SCHEMA', where, 'credentials must be a list')
                used = []
            for cid in used:
                self.ref(where, cid, credentials, 'credential')
            for aid in o.get('assets', []):
                self.ref(where, aid, assets, 'asset')
            if owner_only is True and principal is not None \
                    and principal.get('owner_authority') is not True:
                self.add('OWNER_ONLY_PRINCIPAL', where,
                         f'an Owner-only operation is assigned to {pid}, '
                         'which holds no Owner authority')
            if principal is not None and principal.get('agent_controlled') is True:
                if owner_only is True:
                    self.add('AGENT_OWNER_ONLY', where,
                             f'an Owner-only operation is assigned to agent principal {pid}')
                for cid in used:
                    if credentials.get(cid, {}).get('authority') in PRIVILEGED_AUTHORITIES:
                        self.add('AGENT_PRIVILEGED_CREDENTIAL', where,
                                 f'agent principal {pid} would use privileged credential {cid}')
            if owner_only is True:
                for cid in used:
                    cred = credentials.get(cid)
                    if cred is None:
                        continue
                    agents = [p for p in self.custody(cred) if self.agent(principals, p)]
                    if agents:
                        self.add('AGENT_OWNER_ONLY', where,
                                 f'Owner-only operation uses {cid}, which agent principal(s) '
                                 f'{sorted(set(agents))} hold, manage or may read')
            self.check_status(where, o, findings)

    def check_readme(self):
        if self.readme is None:
            return
        for name in ('operations', 'findings'):
            for entry in self.items(name):
                ident = entry.get('id') if isinstance(entry, dict) else None
                if isinstance(ident, str) and f'`{ident}`' not in self.readme:
                    self.add('README_MISSING', f'{name}.{ident}',
                             'the README does not name this entry (as `id`)')


def check(inventory, root, readme_text=None):
    """Return the problems found in ``inventory`` (a parsed JSON value)."""
    return Checker(inventory, root, readme_text).run()


def summary(inventory):
    ops = [o for o in inventory.get('operations', []) if isinstance(o, dict)]
    fnd = [f for f in inventory.get('findings', []) if isinstance(f, dict)]
    kinds = {}
    for f in fnd:
        kinds[f.get('kind')] = kinds.get(f.get('kind'), 0) + 1
    statuses = {}
    for name in COLLECTIONS[:-1]:
        for e in inventory.get(name, []):
            if isinstance(e, dict):
                statuses[e.get('status')] = statuses.get(e.get('status'), 0) + 1
    return (f"{len(inventory.get('trust_domains', []))} trust domains, "
            f"{len(inventory.get('principals', []))} principals, "
            f"{len(inventory.get('credentials', []))} credentials, "
            f"{len(inventory.get('assets', []))} assets, "
            f"{len(ops)} privileged operations "
            f"({sum(1 for o in ops if o.get('owner_only') is True)} Owner-only), "
            f"{len(fnd)} findings ("
            + ', '.join(f'{k} {v}' for k, v in sorted(kinds.items(), key=str)) + '); statuses: '
            + ', '.join(f'{k} {v}' for k, v in sorted(statuses.items(), key=str)))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--root', default='.', help='repository root (default: .)')
    parser.add_argument('--inventory', help='inventory file (default: <root>/security/inventory.json)')
    parser.add_argument('--readme', help='README naming every operation and finding '
                        '(default: the inventory\'s "readme" entry under the root)')
    parser.add_argument('--list', action='store_true',
                        help='also print each privileged operation with its principal')
    args = parser.parse_args(argv)
    root = Path(args.root)
    path = Path(args.inventory) if args.inventory else root / DEFAULT_INVENTORY
    try:
        inventory = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        print(f'ERROR: cannot read {path}: {exc}', file=sys.stderr)
        return 2
    readme_rel = args.readme or (inventory.get('readme') if isinstance(inventory, dict) else None)
    readme_text = None
    if readme_rel:
        readme_path = Path(args.readme) if args.readme else root / readme_rel
        try:
            readme_text = readme_path.read_text(encoding='utf-8')
        except OSError as exc:
            print(f'ERROR: cannot read {readme_path}: {exc}', file=sys.stderr)
            return 2
    problems = check(inventory, root, readme_text)
    if args.list and isinstance(inventory, dict):
        for o in inventory.get('operations', []):
            if isinstance(o, dict):
                flag = ' [Owner-only]' if o.get('owner_only') is True else ''
                print(f"{o.get('id')}: {o.get('principal')} ({o.get('status')}){flag}")
    for problem in problems:
        print(f'FAIL {problem}')
    if problems:
        print(f'FAIL {path.as_posix()}: {len(problems)} problem(s)')
        return 1
    print(f'PASS {path.as_posix()}: {summary(inventory)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
