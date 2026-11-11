"""Check the minimal versioned control catalog (plan leaf G-01.1).

``policy/control-catalog.json`` declares the governance controls: isolation, credentials,
CI, code review, authorization, evidence and recovery, each with its objective (``purpose``),
its subject (typed by the lineage reference kinds of ``integrations/lineage/lineage_schema.json``,
P-03.1/P-03.2), its enforcement points (a boundary, the enforcing principal of the security
inventory, its assets and the plan leaves that build it) and its applicability (the risk
profiles and the events that bring it into force). It also declares the profiles and how a
profile is resolved, the exception classes and the catalog's admission. ``policy/
control-catalog.md`` renders it. This checker enforces the leaf's acceptance mechanically:
every required control has an objective subject, an enforcement boundary and applicability
criteria. It checks definitions only; whether a control is enforced is evidence, which G-01.2
links, and no definition here is evidence of enforcement.

It fails when:

- a required category (the leaf's seven) has no control, or the catalog's categories,
  boundaries or exception classes differ from the closed sets;
- a control has no objective (``purpose``), no subject, or a subject kind that is not a
  lineage reference kind or whose native identity the lineage schema leaves unsettled;
- a control has no applicability (no profile or no event), names an unknown profile, or is a
  non-waivable control that does not apply always (baseline);
- a control has no enforcement point, or one whose boundary is not a declared boundary, whose
  principal is agent-controlled or not in a trusted, trusted-computing-base or contained trust
  domain, or that names no asset, mechanism or building plan leaf;
- an isolation or credentials control allows an exception (a waiver never overrides physical
  isolation or unauthorized credential access), or an ``unsettled`` exception names no plan
  leaf that settles it;
- the profiles are malformed: not exactly one ``baseline`` that applies always, a condition on
  an undeclared classification input, or a profile that no control applies in;
- the rule authority or the exception authority is not the principal of the inventory's
  Owner-only policy-change operation; the admission names another performer or operation, or
  names the planned performer of the protected authorization merge (the authorization
  recorder has no authority over catalog admission; M-5, 2026-11-11); an ``admitted`` catalog
  cites no Owner approval that occurs verbatim in the bootstrap log;
- an id does not resolve (principal, asset, plan leaf, link, blueprint anchor), an id is
  malformed or duplicated, a key is unknown, the OSCAL block claims to be OSCAL, a machine path
  appears, or the README omits a control id or its generated tables differ from ``--render``.

It needs only the standard library and reads nothing outside the repository.

Usage (from the repository root):
    python -I -B tools/check_control_catalog.py [--catalog FILE] [--root DIR] [--list] [--render]

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

SCHEMA = 'ai-engineering-harness/policy/control-catalog/v1'
DEFAULT_CATALOG = Path('policy') / 'control-catalog.json'
LINEAGE_SCHEMA = 'integrations/lineage/lineage_schema.json'
BOOTSTRAP_LOG = 'evidence/bootstrap-log.md'

# The leaf's action: "Declare isolation, credentials, CI, code review, authorization, evidence
# and recovery controls" (plan G-01.1).
CATEGORIES = ('isolation', 'credentials', 'ci', 'code-review', 'authorization', 'evidence',
              'recovery')
# "Waivers must not override physical isolation or unauthorized credential access"
# (blueprint #governance-architecture).
NON_WAIVABLE = ('isolation', 'credentials')
# The enforcing boundaries of blueprint #security (3 to 6); planning (2) enforces nothing.
BOUNDARIES = ('execution', 'git-ci', 'effect', 'evidence')
EXCEPTION_CLASSES = ('prohibited', 'scoped', 'unsettled')
EXCEPTION_FIELDS = ('control', 'target', 'reason', 'residual_risk', 'compensating_measures',
                    'expires_at')
# "resolved deterministically from repository classification, change surface, target
# environment, risk and operation type" (blueprint #control-evidence).
CLASSIFICATION_INPUTS = ('repository-classification', 'change-surface', 'target-environment',
                         'risk', 'operation-type')
BASELINE = 'baseline'
ENFORCER_TRUST = ('trusted', 'trusted-computing-base', 'contained')
ADMISSION_STATUSES = ('proposed', 'admitted')
POLICY_CHANGE = 'op-policy-change'
PROTECTED_MERGE = 'op-protected-merge'

CONTROL_ID = re.compile(r'^[A-Z]+(-[A-Z]+)*-[0-9]{2}$')
TOP_KEYS = {'schema', 'plan_leaf', 'title', 'as_of', 'baseline_commit', 'inventory',
            'lineage_schema', 'readme', 'checker', 'statement', 'reference_form', 'authority',
            'admission', 'categories', 'boundaries', 'exception_classes', 'exception_contract',
            'classification_inputs', 'profiles', 'resolution', 'controls', 'deferred_controls',
            'oscal', 'sources'}
CONTROL_KEYS = {'id', 'title', 'category', 'purpose', 'subject', 'applicability', 'enforcement',
                'exception', 'exception_settled_at', 'failure_effect', 'sources'}
ENFORCEMENT_KEYS = {'boundary', 'principal', 'assets', 'mechanism', 'builds_at'}
PROFILE_KEYS = {'id', 'name', 'applies', 'obligations', 'sources'}
ADMISSION_KEYS = {'status', 'performer', 'operation', 'repository', 'realization', 'approval',
                  'sources'}
DEFERRED_KEYS = {'id', 'title', 'reason', 'leaves'}
APPROVAL_KEYS = {'link', 'quote'}

GENERATED_BEGIN = '<!-- BEGIN GENERATED: python -I -B tools/check_control_catalog.py --render -->'
GENERATED_END = '<!-- END GENERATED -->'


def _list(value):
    return value if isinstance(value, list) else []


def _dict(value):
    return value if isinstance(value, dict) else {}


def _str(value):
    return value if isinstance(value, str) else ''


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _in(key, table):
    return isinstance(key, str) and key in table


def lineage_kinds(schema):
    """{kind: settled} of the lineage schema's reference kinds."""
    out = {}
    for k in _list(_dict(schema).get('kinds')):
        if isinstance(k, dict) and isinstance(k.get('kind'), str):
            out[k['kind']] = _dict(k.get('identity')).get('settled') is True
    return out


class Checker(csi.Checker):
    """Reuses the inventory checker's id tables, link, plan-id and machine-path helpers."""

    def __init__(self, catalog, inventory, root, readme_text=None, lineage=None, files=None):
        super().__init__(inventory, root, readme_text, files)
        self.catalog = catalog
        self.kinds = lineage_kinds(lineage)

    def check_link(self, where, link):
        """The inventory checker's link rule, remembered per link on the shared files (a link's
        verdict depends only on the tree; the anchor search of the blueprint dominates)."""
        memo = self.files.__dict__.setdefault('_link_verdicts', {})
        if isinstance(link, str) and link in memo:
            for code, message in memo[link]:
                self.add(code, where, message)
            return
        before = len(self.problems)
        super().check_link(where, link)
        if isinstance(link, str):
            memo[link] = [(p.code, p.message) for p in self.problems[before:]]

    def keys(self, where, entry, allowed):
        for key in entry:
            if key not in allowed:
                self.add('SCHEMA', where, f'unknown key {key!r}')

    def words(self, value):
        """A non-empty list of non-empty strings, or None."""
        if isinstance(value, list) and value and all(_text(v) for v in value):
            return value
        return None

    def leaves(self, where, value, what):
        found = self.words(value)
        if found is None:
            self.add('DANGLING_REF', where, f'{what} must name at least one plan leaf')
            return
        for leaf in found:
            if leaf not in self.plan:
                self.add('DANGLING_REF', where, f'{what} {leaf!r} is not a plan leaf')

    def sources(self, where, entry):
        if not self.words(entry.get('sources')):
            self.add('SCHEMA', where, 'sources must name at least one link')
            return
        self.check_links(where, entry, 'sources')

    def closed(self, key, expected):
        value = _dict(self.catalog.get(key))
        if sorted(value) != sorted(expected) or not all(_text(v) for v in value.values()):
            self.add('SCHEMA', key, f'must describe exactly {list(expected)}')

    # -- the checks --------------------------------------------------------------

    def run(self):
        c = self.catalog
        if not isinstance(c, dict):
            self.add('SCHEMA', 'catalog', 'the catalog must be a JSON object')
            return self.problems
        if c.get('schema') != SCHEMA:
            self.add('SCHEMA', 'schema', f'expected {SCHEMA!r}')
        self.keys('catalog', c, TOP_KEYS)
        for key in ('inventory', 'lineage_schema', 'readme', 'checker'):
            self.check_link(key, c.get(key))
        self.sources('catalog', c)
        self.check_machine_paths(c, 'catalog')
        if not self.kinds:
            self.add('SCHEMA', 'lineage_schema', f'cannot read the lineage kinds of {LINEAGE_SCHEMA}')
        self.closed('categories', CATEGORIES)
        self.closed('boundaries', BOUNDARIES)
        self.closed('exception_classes', EXCEPTION_CLASSES)
        self.closed('classification_inputs', CLASSIFICATION_INPUTS)

        self.principals = self.index('principals')
        self.domains = self.index('trust_domains')
        self.assets = self.index('assets')
        self.ops = self.index('operations')
        self.plan = self.plan_ids() or set()
        self.authority = self.check_authority()
        self.check_admission()
        profiles = self.check_profiles()
        self.check_resolution()
        controls = _list(c.get('controls'))
        if not controls:
            self.add('SCHEMA', 'controls', 'must be a non-empty list')
        seen = {}
        for collection, rows in (('controls', controls),
                                 ('deferred_controls', _list(c.get('deferred_controls')))):
            for n, row in enumerate(rows):
                where = f'{collection}[{n}]'
                if not isinstance(row, dict):
                    self.add('SCHEMA', where, 'must be an object')
                    continue
                ident = row.get('id')
                if not isinstance(ident, str) or not CONTROL_ID.match(ident):
                    self.add('ID_INVALID', where, f'id {ident!r} must look like EXEC-01')
                else:
                    if ident in seen:
                        self.add('ID_DUPLICATE', where, f'id {ident!r} is also {seen[ident]}')
                    seen[ident] = where
                    where = f'{collection}.{ident}'
                if collection == 'controls':
                    self.check_control(where, row, profiles)
                else:
                    self.check_deferred(where, row)
        self.check_coverage(controls, profiles)
        self.check_oscal()
        self.check_catalog_readme()
        return self.problems

    def check_authority(self):
        """The rule authority is the principal of the inventory's Owner-only policy change."""
        a = _dict(self.catalog.get('authority'))
        op = _dict(self.ops.get(POLICY_CHANGE))
        principal = op.get('principal')
        if op.get('owner_only') is not True:
            self.add('AUTHORITY', 'authority', f'the inventory has no Owner-only {POLICY_CHANGE}')
        if a.get('operation') != POLICY_CHANGE or a.get('principal') != principal:
            self.add('AUTHORITY', 'authority', f'the rule authority is {principal!r} through '
                     f'{POLICY_CHANGE}, the inventory\'s Owner-only policy change')
        contract = _dict(self.catalog.get('exception_contract'))
        if contract.get('authority') != principal:
            self.add('AUTHORITY', 'exception_contract', f'only {principal!r}, the rule authority, '
                     'grants an exception')
        if _list(contract.get('fields')) != list(EXCEPTION_FIELDS) or not _text(contract.get('rule')):
            self.add('SCHEMA', 'exception_contract', f'fields must be {list(EXCEPTION_FIELDS)}, '
                     'with the rule')
        self.sources('exception_contract', contract)
        return principal

    def check_admission(self):
        where = 'admission'
        a = self.catalog.get('admission')
        if not isinstance(a, dict):
            self.add('SCHEMA', where, 'must be an object')
            return
        self.keys(where, a, ADMISSION_KEYS)
        if a.get('operation') != POLICY_CHANGE or a.get('performer') != self.authority:
            self.add('ADMISSION_AUTHORITY', where, f'the catalog is admitted by {self.authority!r} '
                     f'through {POLICY_CHANGE}, never by another principal')
        merger = _dict(self.ops.get(PROTECTED_MERGE)).get('planned_performer')
        if merger in (a.get('performer'), self.authority):
            self.add('ADMISSION_AUTHORITY', where, f'{merger!r} performs {PROTECTED_MERGE} only; '
                     'it has no authority over catalog admission (M-5, 2026-11-11)')
        asset = self.assets.get(a.get('repository')) if _in(a.get('repository'), self.assets) else None
        if _dict(asset).get('kind') != 'repository':
            self.add('DANGLING_REF', where, f"repository {a.get('repository')!r} is not an "
                     'inventory repository')
        if not _text(a.get('realization')):
            self.add('SCHEMA', where, 'realization is required')
        self.sources(where, a)
        status = a.get('status')
        if status not in ADMISSION_STATUSES:
            self.add('SCHEMA', where, f'status {status!r} is not one of {ADMISSION_STATUSES}')
        elif status == 'admitted':
            self.check_owner_approval(where, a.get('approval'))
        elif 'approval' in a:
            self.add('SCHEMA', where, 'a proposed catalog carries no approval')

    def check_owner_approval(self, where, approval):
        if not isinstance(approval, dict) or set(approval) != APPROVAL_KEYS or \
                approval.get('link') != BOOTSTRAP_LOG or not isinstance(approval.get('quote'), str) \
                or len(approval.get('quote').strip()) < 12:
            self.add('OWNER_APPROVAL', where, f'an admitted catalog cites the Owner sign-off: '
                     f'{{link: {BOOTSTRAP_LOG}, quote: <the sign-off, verbatim>}}')
            return
        text = self.read_text(BOOTSTRAP_LOG)
        if text is None or approval['quote'] not in text:
            self.add('OWNER_APPROVAL', where, f'the quoted sign-off is not in {BOOTSTRAP_LOG}')

    def check_profiles(self):
        out = {}
        rows = _list(self.catalog.get('profiles'))
        always = []
        for n, p in enumerate(rows):
            where = f'profiles[{n}]'
            if not isinstance(p, dict) or not isinstance(p.get('id'), str) or \
                    not csi.ID.match(p.get('id')) or p.get('id') in out:
                self.add('PROFILE_INVALID', where, 'a profile is an object with a unique '
                         'kebab-case id')
                continue
            out[p['id']] = p
            where = f"profiles.{p['id']}"
            self.keys(where, p, PROFILE_KEYS)
            for key in ('name', 'obligations'):
                if not _text(p.get(key)):
                    self.add('PROFILE_INVALID', where, f'{key} is required')
            applies = p.get('applies')
            if applies == 'always':
                always.append(p['id'])
            elif not isinstance(applies, dict) or set(applies) != {'input', 'any_of'} or \
                    applies.get('input') not in CLASSIFICATION_INPUTS or \
                    not self.words(applies.get('any_of')):
                self.add('PROFILE_INVALID', where, 'applies is "always" or {input: <a '
                         'classification input>, any_of: [<values>]}')
            self.sources(where, p)
        if always != [BASELINE]:
            self.add('PROFILE_INVALID', 'profiles', f'exactly one profile, {BASELINE!r}, applies '
                     f'always (found {always})')
        return out

    def check_resolution(self):
        r = _dict(self.catalog.get('resolution'))
        for key in ('rule', 'unknown', 'downgrade'):
            if not _text(r.get(key)):
                self.add('SCHEMA', 'resolution', f'{key} is required: how a profile is resolved, '
                         'what an unknown input selects, and that no agent downgrades a control')
        self.sources('resolution', r)

    def check_control(self, where, row, profiles):
        self.keys(where, row, CONTROL_KEYS)
        if not _text(row.get('title')):
            self.add('SCHEMA', where, 'title is required')
        category = row.get('category')
        if not _in(category, CATEGORIES):
            self.add('SCHEMA', where, f'category {category!r} is not one of {CATEGORIES}')
        if not _text(row.get('purpose')):
            self.add('OBJECTIVE_MISSING', where, 'a control states its objective (purpose)')
        self.check_subject(where, row.get('subject'))
        applies = self.check_applicability(where, row.get('applicability'), profiles)
        self.check_enforcement(where, row.get('enforcement'))
        exception = row.get('exception')
        if exception not in EXCEPTION_CLASSES:
            self.add('SCHEMA', where, f'exception {exception!r} is not one of {EXCEPTION_CLASSES}')
        if _in(category, NON_WAIVABLE):
            if exception != 'prohibited':
                self.add('EXCEPTION_FORBIDDEN', where, f'a {category} control is non-waivable: '
                         'its exception is prohibited')
            if BASELINE not in applies:
                self.add('APPLICABILITY_NARROW', where, f'a non-waivable control applies always '
                         f'({BASELINE})')
        if exception == 'unsettled':
            leaf = row.get('exception_settled_at')
            if not _in(leaf, self.plan):
                self.add('EXCEPTION_UNSETTLED', where, 'an unsettled exception names the plan leaf '
                         'that settles it (exception_settled_at)')
        elif 'exception_settled_at' in row:
            self.add('SCHEMA', where, 'exception_settled_at belongs to an unsettled exception')
        if not _text(row.get('failure_effect')):
            self.add('SCHEMA', where, 'failure_effect is required')
        self.sources(where, row)

    def check_subject(self, where, subject):
        if not isinstance(subject, dict) or set(subject) != {'kinds', 'scope'} or \
                not _text(subject.get('scope')) or not self.words(subject.get('kinds')):
            self.add('SUBJECT_INVALID', where, 'subject is {kinds: [<lineage kinds>], scope: <text>}')
            return
        for kind in subject['kinds']:
            if kind not in self.kinds:
                self.add('SUBJECT_INVALID', where, f'subject kind {kind!r} is not a lineage '
                         f'reference kind of {LINEAGE_SCHEMA}')
            elif not self.kinds[kind]:
                self.add('SUBJECT_UNSETTLED', where, f'the lineage schema leaves the native '
                         f'identity of {kind!r} unsettled, so the subject is not objective')

    def check_applicability(self, where, value, profiles):
        if not isinstance(value, dict) or set(value) != {'profiles', 'events'} or \
                not self.words(value.get('profiles')) or not self.words(value.get('events')):
            self.add('APPLICABILITY_MISSING', where, 'applicability is {profiles: [<profile ids>], '
                     'events: [<what brings the control into force>]}')
            return set()
        for pid in value['profiles']:
            if pid not in profiles:
                self.add('DANGLING_REF', where, f'profile {pid!r} is not declared')
        return set(value['profiles'])

    def check_enforcement(self, where, value):
        if not isinstance(value, list) or not value:
            self.add('ENFORCEMENT_MISSING', where, 'a control names at least one enforcement point')
            return
        for n, e in enumerate(value):
            w = f'{where}.enforcement[{n}]'
            if not isinstance(e, dict):
                self.add('ENFORCEMENT_INVALID', w, 'must be an object')
                continue
            self.keys(w, e, ENFORCEMENT_KEYS)
            if e.get('boundary') not in BOUNDARIES:
                self.add('ENFORCEMENT_INVALID', w, f'boundary must be one of {BOUNDARIES}')
            if not _text(e.get('mechanism')):
                self.add('ENFORCEMENT_INVALID', w, 'mechanism is required')
            principal = self.ref(w, e.get('principal'), self.principals, 'principal')
            if principal is not None:
                trust = _dict(self.domains.get(principal.get('domain'))
                              if _in(principal.get('domain'), self.domains) else None).get('trust')
                if principal.get('agent_controlled') is not False or trust not in ENFORCER_TRUST:
                    self.add('ENFORCER_UNTRUSTED', w, f"{e.get('principal')!r} (trust {trust!r}) "
                             'cannot enforce a control: an agent-controlled principal or an '
                             'untrusted domain never is the guard')
            assets = self.words(e.get('assets'))
            if assets is None:
                self.add('ENFORCEMENT_INVALID', w, 'assets must name the enforcing assets')
            for aid in assets or []:
                self.ref(w, aid, self.assets, 'asset')
            self.leaves(w, e.get('builds_at'), 'builds_at')

    def check_deferred(self, where, row):
        self.keys(where, row, DEFERRED_KEYS)
        for key in ('title', 'reason'):
            if not _text(row.get(key)):
                self.add('SCHEMA', where, f'{key} is required')
        self.leaves(where, row.get('leaves'), 'leaves')

    def check_coverage(self, controls, profiles):
        rows = [r for r in controls if isinstance(r, dict)]
        for category in CATEGORIES:
            if not any(r.get('category') == category for r in rows):
                self.add('CATEGORY_UNCOVERED', category, 'a required category has no control')
        for pid in profiles:
            if not any(pid in _list(_dict(r.get('applicability')).get('profiles')) for r in rows):
                self.add('PROFILE_EMPTY', f'profiles.{pid}', 'no control applies in this profile')

    def check_oscal(self):
        o = _dict(self.catalog.get('oscal'))
        if o.get('claim') != 'none':
            self.add('SCHEMA', 'oscal', 'the catalog never claims to be an OSCAL document '
                     '(claim: none)')
        fields = _dict(o.get('fields'))
        if not {'id', 'title', 'purpose'} <= set(fields) or not set(fields) <= CONTROL_KEYS:
            self.add('SCHEMA', 'oscal.fields', 'maps control keys (at least id, title, purpose)')

    def check_catalog_readme(self):
        if self.readme is None:
            return
        if csi.MACHINE_PATH.search(self.readme):
            self.add('MACHINE_PATH', 'readme', 'a machine-specific path must not be published')
        for collection in ('controls', 'deferred_controls'):
            for r in _list(self.catalog.get(collection)):
                ident = r.get('id') if isinstance(r, dict) else None
                if isinstance(ident, str) and f'`{ident}`' not in self.readme:
                    self.add('README_MISSING', ident, 'the README does not name this control '
                             '(as `id`)')
        block = generated_block(self.readme)
        if block is None:
            self.add('README_STALE', 'readme', 'the generated tables are missing their markers')
        elif block.strip() != render(self.catalog).strip():
            self.add('README_STALE', 'readme', 'the generated tables differ from --render; '
                     're-render them from the catalog')


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


def render(catalog):
    """The README's generated tables, rendered from the catalog."""
    catalog = _dict(catalog)
    rows = [r for r in _list(catalog.get('controls')) if isinstance(r, dict)]
    out = ['', '### Controls', '',
           '| Control | Category | Objective | Subject | Applies in | Events | Exception |',
           '|---|---|---|---|---|---|---|']
    for r in rows:
        subject = _dict(r.get('subject'))
        applicability = _dict(r.get('applicability'))
        exception = _str(r.get('exception'))
        if r.get('exception_settled_at'):
            exception += f" (settled at {r.get('exception_settled_at')})"
        out.append(f"| `{r.get('id')}` {_cell(_str(r.get('title')))} | {r.get('category')} | "
                   f"{_cell(_str(r.get('purpose')))} | {_ids(subject.get('kinds'))}: "
                   f"{_cell(_str(subject.get('scope')))} | {_ids(applicability.get('profiles'))} | "
                   f"{_cell('; '.join(str(e) for e in _list(applicability.get('events'))))} | "
                   f'{_cell(exception)} |')
    out += ['', '### Enforcement points', '',
            '| Control | Boundary | Enforcing principal | Assets | Mechanism | Built at |',
            '|---|---|---|---|---|---|']
    for r in rows:
        for e in _list(r.get('enforcement')):
            if isinstance(e, dict):
                out.append(f"| `{r.get('id')}` | {e.get('boundary')} | `{e.get('principal')}` | "
                           f"{_ids(e.get('assets'))} | {_cell(_str(e.get('mechanism')))} | "
                           f"{', '.join(str(x) for x in _list(e.get('builds_at'))) or '-'} |")
    out += ['', '### Profiles', '', '| Profile | Applies when | Obligations | Controls |',
            '|---|---|---|---|']
    for p in _list(catalog.get('profiles')):
        if not isinstance(p, dict):
            continue
        applies = p.get('applies')
        if isinstance(applies, dict):
            applies = f"{applies.get('input')} is any of " + ', '.join(
                str(v) for v in _list(applies.get('any_of')))
        names = [r.get('id') for r in rows
                 if p.get('id') in _list(_dict(r.get('applicability')).get('profiles'))]
        out.append(f"| `{p.get('id')}` {_cell(_str(p.get('name')))} | {_cell(applies)} | "
                   f"{_cell(_str(p.get('obligations')))} | {_ids(names)} |")
    out += ['', '### Deferred controls', '', '| Control | Why not here | Leaves |', '|---|---|---|']
    for d in _list(catalog.get('deferred_controls')):
        if isinstance(d, dict):
            out.append(f"| `{d.get('id')}` {_cell(_str(d.get('title')))} | "
                       f"{_cell(_str(d.get('reason')))} | "
                       f"{', '.join(str(x) for x in _list(d.get('leaves')))} |")
    out.append('')
    return '\n'.join(out)


def summary(catalog):
    rows = [r for r in _list(_dict(catalog).get('controls')) if isinstance(r, dict)]
    exceptions = {}
    for r in rows:
        key = r.get('exception') if isinstance(r.get('exception'), str) else repr(r.get('exception'))
        exceptions[key] = exceptions.get(key, 0) + 1
    categories = {r.get('category') for r in rows if isinstance(r.get('category'), str)}
    return (f'{len(rows)} controls in {len(categories)} categories; exceptions: '
            + ', '.join(f'{k} {v}' for k, v in sorted(exceptions.items())) +
            f"; {len(_list(_dict(catalog).get('deferred_controls')))} deferred; admission "
            f"{_dict(_dict(catalog).get('admission')).get('status')}")


class Inputs:
    """What a catalog is checked against, loaded once under a root (the load/evaluate seam): the
    lineage schema and the repository files the checks read (``csi.RepoFiles``)."""

    def __init__(self, root, lineage, files):
        self.root, self.lineage, self.files = root, lineage, files


def load_inputs(root):
    files = csi.RepoFiles(root)
    try:
        lineage = json.loads(files.read_text(LINEAGE_SCHEMA) or '')
    except ValueError:
        lineage = {}
    return Inputs(root, lineage, files)


def evaluate(catalog, inventory, inputs, readme_text=None):
    """Return the problems found in ``catalog`` against ``inventory`` and already-loaded INPUTS
    (``load_inputs``). Reads nothing that INPUTS has read already, and changes none of them."""
    return Checker(catalog, inventory, inputs.root, readme_text, inputs.lineage,
                   files=inputs.files).run()


def check(catalog, inventory, root, readme_text=None):
    """Return the problems found in ``catalog`` against ``inventory`` (parsed JSON values)."""
    return evaluate(catalog, inventory, load_inputs(root), readme_text)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--root', default='.', help='repository root (default: .)')
    parser.add_argument('--catalog', help='catalog file (default: <root>/policy/control-catalog.json)')
    parser.add_argument('--inventory', help='security inventory (default: the catalog\'s '
                        '"inventory" entry under the root)')
    parser.add_argument('--readme', help='README naming every control (default: the catalog\'s '
                        '"readme" entry under the root)')
    parser.add_argument('--list', action='store_true',
                        help='also print each control with its subject, profiles and enforcers')
    parser.add_argument('--render', action='store_true',
                        help='print the README\'s generated tables and exit')
    args = parser.parse_args(argv)
    root = Path(args.root)
    path = Path(args.catalog) if args.catalog else root / DEFAULT_CATALOG
    try:
        catalog = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        print(f'ERROR: cannot read {path}: {exc}', file=sys.stderr)
        return 2
    if args.render:
        sys.stdout.write(render(catalog))
        return 0
    inv_rel = catalog.get('inventory') if isinstance(catalog, dict) else None
    inv_path = Path(args.inventory) if args.inventory else root / (inv_rel or csi.DEFAULT_INVENTORY)
    try:
        inventory = json.loads(inv_path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        print(f'ERROR: cannot read {inv_path}: {exc}', file=sys.stderr)
        return 2
    if not isinstance(inventory, dict):
        print(f'ERROR: {inv_path} is not a JSON object', file=sys.stderr)
        return 2
    readme_rel = args.readme or (catalog.get('readme') if isinstance(catalog, dict) else None)
    readme_text = None
    if readme_rel:
        readme_path = Path(args.readme) if args.readme else root / readme_rel
        try:
            readme_text = readme_path.read_text(encoding='utf-8')
        except OSError as exc:
            print(f'ERROR: cannot read {readme_path}: {exc}', file=sys.stderr)
            return 2
    problems = check(catalog, inventory, root, readme_text)
    if args.list and isinstance(catalog, dict):
        for r in _list(catalog.get('controls')):
            if isinstance(r, dict):
                enforcers = ', '.join(f"{e.get('boundary')}:{e.get('principal')}"
                                      for e in _list(r.get('enforcement')) if isinstance(e, dict))
                print(f"{r.get('id')} ({r.get('category')}): "
                      f"{', '.join(map(str, _list(_dict(r.get('subject')).get('kinds'))))}; "
                      f"{', '.join(map(str, _list(_dict(r.get('applicability')).get('profiles'))))}; "
                      f"{enforcers}; exception {r.get('exception')}")
    for problem in problems:
        print(f'FAIL {problem}')
    if problems:
        print(f'FAIL {path.as_posix()}: {len(problems)} problem(s)')
        return 1
    print(f'PASS {path.as_posix()}: {summary(catalog)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
