"""Check the role-token matrix and revocation contract (plan leaf S-01.2.1).

``policy/role-tokens.json`` binds each role to exactly one principal of the security
inventory (``security/inventory.json``, S-01.1) and grants it inventory operations
(``op-*``), named capabilities (``cap-*``) and credentials (``cred-*``). It also
records each credential's issuance and revocation, how each role is to be realized
(verified only with evidence, by S-01.2.2 and later leaves), and, for the host-side bootstrap agents, the leaf at which each
operation they perform today moves to its planned principal. ``policy/README.md`` is
its human-readable record. This checker enforces the leaf's acceptance mechanically:
no agent, reviewer or CI role has Owner or privileged-effect capability in the
documented mapping.

It fails when:

- a role binds to a missing principal, or grants or denies an id that does not exist;
- an agent-controlled role is granted an Owner-only operation, an executor operation,
  ``op-gitea-administration``, an ``op-as-*`` operation, ``cap-code-merge-integration``
  or another capability of privileged authority, or a credential of Owner, admin,
  executor or management authority; or a provider credential (never a role token);
- a grant is made to a principal that is not independently isolated (the bootstrap
  agents are a non-role row with no grants);
- a granted operation's inventory principal is not the role's principal;
- an agent-controlled role omits a baseline denial, or grants what it denies;
- a credential's issuance or revocation row is missing, names another issuer than the
  inventory, has a revoker other than the issuer's role, uses an unknown trigger, or
  has a rotation owner that is null without a finding or differs from the inventory,
  or sends a receipt to the effects store for anything but an executor credential;
- a realization marked verified lacks evidence;
- the sunset map misses a planned operation that the Owner's account performs today;
- an inventory operation or credential is mapped to no role, or a row carries an
  exclusion flag or an unknown key;
- a status, link, anchor or plan id fails the inventory's rules;
- a machine path appears; or the README omits a role or capability id, or its
  generated tables differ from ``--render``.

It needs only the standard library and reads nothing outside the repository.

Usage (from the repository root):
    python -I -B tools/check_role_tokens.py [--policy FILE] [--root DIR] [--list] [--render]

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

SCHEMA = 'ai-engineering-harness/policy/role-tokens/v1'
DEFAULT_POLICY = Path('policy') / 'role-tokens.json'
DEFAULT_INVENTORY = csi.DEFAULT_INVENTORY

TRIGGERS = ('attempt-end', 'suspected-exposure', 'definition-revocation', 'policy-revision',
            'expiry', 'owner-direction')
REQUIRED_TRIGGERS = ('suspected-exposure', 'owner-direction')
AGENT_REQUIRED_TRIGGERS = ('attempt-end',)
NEW_DISPATCH = 'immediate-refusal'
RECEIPT_STORES = ('integration-store', 'effects-store')

CODE_MERGE = 'cap-code-merge-integration'
GITEA_ADMIN = 'op-gitea-administration'
MANAGEMENT_PREFIX = 'op-as-'
# What every agent-controlled role must deny explicitly in the documented mapping:
# merges, protected-ref push, administration and protection changes, the executor, the
# management session key, Docker, and the Owner's and administrator's credentials.
AGENT_BASELINE_DENIALS = (
    'op-protected-merge', CODE_MERGE, 'cap-protected-ref-push', GITEA_ADMIN,
    'op-effect-apply', 'op-effect-receipt-write', 'cred-executor-identity',
    'cred-agent-server-session-key', 'op-as-conversation-create', 'cred-moby-docker-group',
    'cred-gitea-owner-account', 'cred-gitea-admin')

CAP_ID = re.compile(r'^cap-[a-z0-9]+(-[a-z0-9]+)*$')
EXCLUSION_KEY = re.compile(r'exclu|exempt|waive|skip|ignore|out.?of.?scope', re.IGNORECASE)
TOP_KEYS = {'schema', 'plan_leaf', 'title', 'as_of', 'baseline_commit', 'inventory', 'readme',
            'checker', 'decision', 'trigger_classes', 'revocation_contract', 'capabilities',
            'roles', 'non_roles', 'sources', 'notes'}
ROLE_KEYS = {'id', 'name', 'principal', 'agent_controlled', 'grants', 'custodian_of', 'denied',
             'realization', 'issuance', 'revocation', 'target', 'bootstrap', 'invariants',
             'status', 'sources', 'evidence', 'findings', 'notes'}
NON_ROLE_KEYS = {'id', 'name', 'principal', 'grants', 'inherits_reach_of', 'sunset', 'status',
                 'sources', 'evidence', 'findings', 'notes'}
CAPABILITY_KEYS = {'id', 'name', 'authority', 'description', 'delegation', 'status', 'sources',
                   'evidence', 'findings', 'notes'}
GRANT_KEYS = ('operations', 'capabilities', 'credentials')
REALIZATION_KEYS = {'mechanism', 'verified', 'verify_at', 'evidence', 'notes'}
ISSUANCE_KEYS = {'credential', 'issuer', 'delivered_by', 'delivery'}
REVOCATION_KEYS = {'credential', 'triggers', 'revoker', 'method', 'rotation_owner',
                   'receipt_store', 'findings', 'notes'}
BOOTSTRAP_KEYS = {'observed_performer', 'evidence', 'note'}
SUNSET_KEYS = {'scope', 'operations', 'at', 'gap'}

GENERATED_BEGIN = '<!-- BEGIN GENERATED: python -I -B tools/check_role_tokens.py --render -->'
GENERATED_END = '<!-- END GENERATED -->'


def _in(key, table):
    """Membership that tolerates a wrongly typed (unhashable) key."""
    return isinstance(key, str) and key in table


class Checker(csi.Checker):
    """Reuses the inventory checker's id tables, link, status and machine-path helpers."""

    def __init__(self, policy, inventory, root, readme_text=None):
        super().__init__(inventory, root, readme_text)
        self.policy = policy

    # -- helpers -----------------------------------------------------------------

    def rows(self, name):
        value = self.policy.get(name)
        return value if isinstance(value, list) else []

    def keys(self, where, entry, allowed):
        for key in entry:
            if EXCLUSION_KEY.search(key):
                self.add('EXCLUSION_FLAG', where, f'{key!r}: no flag may remove a row from the '
                         'acceptance')
            elif key not in allowed:
                self.add('SCHEMA', where, f'unknown key {key!r}')

    def text(self, where, entry, key):
        if not isinstance(entry.get(key), str) or not entry.get(key).strip():
            self.add('SCHEMA', where, f'{key} is required')

    def id_list(self, where, value):
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            self.add('SCHEMA', where, 'must be a list of ids')
            return []
        if len(set(value)) != len(value):
            self.add('SCHEMA', where, 'lists an id twice')
        return value

    def is_agent(self, pid):
        p = self.principals.get(pid)
        return p is not None and p.get('agent_controlled') is True

    def role_principal(self, rid):
        role = self.roles.get(rid) if isinstance(rid, str) else None
        return role.get('principal') if role else None

    def check_status(self, where, entry, findings):
        for key in ('sources', 'evidence', 'findings'):
            value = entry.get(key, [])
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                self.add('SCHEMA', where, f'{key} must be a list of strings')
                return
        super().check_status(where, entry, findings)

    # -- the checks --------------------------------------------------------------

    def run(self):
        pol = self.policy
        if not isinstance(pol, dict):
            self.add('SCHEMA', 'policy', 'the matrix must be a JSON object')
            return self.problems
        if pol.get('schema') != SCHEMA:
            self.add('SCHEMA', 'schema', f'expected {SCHEMA!r}')
        self.keys('policy', pol, TOP_KEYS)
        for name in ('capabilities', 'roles', 'non_roles'):
            if not isinstance(pol.get(name), list) or not pol.get(name):
                self.add('SCHEMA', name, 'must be a non-empty list')
        classes = pol.get('trigger_classes')
        if not isinstance(classes, dict) or sorted(classes) != sorted(TRIGGERS):
            self.add('SCHEMA', 'trigger_classes', f'must define exactly {list(TRIGGERS)}')
        if not self.check_links('policy', pol, 'sources'):
            self.add('STATUS_UNSUPPORTED', 'policy.sources', 'the matrix needs source links')
        for key in ('inventory', 'readme', 'checker', 'decision'):
            if key in pol:
                self.check_link(key, pol.get(key))
        self.check_machine_paths(pol, 'policy')

        self.principals = self.index('principals')
        self.operations = self.index('operations')
        self.credentials = self.index('credentials')
        self.findings = self.index('findings')
        self.plan = self.plan_ids() or set()
        self.capabilities = self.check_capabilities()
        self.roles = self.check_role_ids()
        self.check_contract()
        for role in self.roles.values():
            self.check_role(role)
        self.check_non_roles()
        self.check_coverage()
        self.check_policy_readme()
        return self.problems

    def check_capabilities(self):
        caps = {}
        for n, cap in enumerate(self.rows('capabilities')):
            where = f'capabilities[{n}]'
            if not isinstance(cap, dict):
                self.add('SCHEMA', where, 'must be an object')
                continue
            ident = cap.get('id')
            if not isinstance(ident, str) or not CAP_ID.match(ident):
                self.add('ID_INVALID', where, f'id {ident!r} must be cap-<kebab-case>')
                continue
            if ident in caps:
                self.add('ID_DUPLICATE', where, f'capability {ident!r} is defined twice')
            caps[ident] = cap
            where = f'capabilities.{ident}'
            self.keys(where, cap, CAPABILITY_KEYS)
            self.text(where, cap, 'name')
            self.text(where, cap, 'description')
            if cap.get('authority') not in csi.AUTHORITIES:
                self.add('SCHEMA', where, f"authority {cap.get('authority')!r} is not one of "
                         f'{csi.AUTHORITIES}')
            delegation = cap.get('delegation')
            if delegation is not None:
                if not isinstance(delegation, dict) or not isinstance(delegation.get('to'), str):
                    self.add('SCHEMA', where, 'delegation needs {by, to}')
                elif not _in(delegation.get('by'), self.plan):
                    self.add('DANGLING_REF', where, f"delegation by {delegation.get('by')!r} is "
                             'not a plan leaf')
            self.check_status(where, cap, self.findings)
        if CODE_MERGE not in caps:
            self.add('SCHEMA', 'capabilities', f'{CODE_MERGE} must be defined')
        return caps

    def check_role_ids(self):
        roles = {}
        for n, role in enumerate(self.rows('roles')):
            where = f'roles[{n}]'
            if not isinstance(role, dict):
                self.add('SCHEMA', where, 'must be an object')
                continue
            ident = role.get('id')
            if not isinstance(ident, str) or not csi.ID.match(ident) or ident.startswith('cap-'):
                self.add('ID_INVALID', where, f'id {ident!r} must be lower-case kebab-case')
                continue
            if ident in roles:
                self.add('ID_DUPLICATE', where, f'role {ident!r} is defined twice')
            roles[ident] = role
        for n, row in enumerate(self.rows('non_roles')):
            ident = row.get('id') if isinstance(row, dict) else None
            if _in(ident, roles):
                self.add('ID_DUPLICATE', f'non_roles[{n}]', f'{ident!r} is also a role')
        return roles

    def check_contract(self):
        contract = self.policy.get('revocation_contract')
        if not isinstance(contract, dict):
            self.add('SCHEMA', 'revocation_contract', 'must be an object')
            return
        if contract.get('new_dispatch') != NEW_DISPATCH:
            self.add('SCHEMA', 'revocation_contract.new_dispatch', f'must be {NEW_DISPATCH!r}')
        if contract.get('receipt_store') != 'integration-store':
            self.add('SCHEMA', 'revocation_contract.receipt_store',
                     'revocation receipts go to the integration store (decision 0004 point 1)')
        for key in ('in_flight', 'evidence', 'receipt_fields'):
            if not isinstance(contract.get(key), list) or not contract.get(key):
                self.add('SCHEMA', f'revocation_contract.{key}', 'must be a non-empty list')
        self.check_links('revocation_contract', contract, 'sources')

    def check_role(self, role):
        rid = role['id']
        where = f'roles.{rid}'
        self.keys(where, role, ROLE_KEYS)
        self.text(where, role, 'name')
        self.text(where, role, 'target')
        pid = role.get('principal')
        principal = self.principals.get(pid) if isinstance(pid, str) else None
        if principal is None:
            self.add('ROLE_PRINCIPAL_MISSING', where,
                     f'principal {pid!r} is not one principal of the inventory')
        elif role.get('agent_controlled') is not principal.get('agent_controlled'):
            self.add('AGENT_CONTROLLED_MISMATCH', where,
                     f'agent_controlled must be {principal.get("agent_controlled")!r}, '
                     f'as for principal {pid}')
        agent = principal is not None and principal.get('agent_controlled') is True

        grants = role.get('grants')
        if not isinstance(grants, dict) or set(grants) != set(GRANT_KEYS):
            self.add('SCHEMA', where, f'grants must be an object with exactly {list(GRANT_KEYS)}')
            grants = {}
        ops = self.id_list(f'{where}.grants.operations', grants.get('operations', []))
        caps = self.id_list(f'{where}.grants.capabilities', grants.get('capabilities', []))
        creds = self.id_list(f'{where}.grants.credentials', grants.get('credentials', []))
        granted = set(ops) | set(caps) | set(creds)

        if principal is not None and principal.get('independently_isolated') is not True \
                and granted:
            self.add('GRANT_NOT_ISOLATED', where,
                     f'principal {pid} is not independently isolated; no grant is made to it')

        for oid in ops:
            op = self.operations.get(oid)
            if op is None:
                self.add('GRANT_MISSING', where, f'operation {oid!r} is not in the inventory')
                continue
            if op.get('principal') != pid:
                self.add('GRANT_PRINCIPAL_MISMATCH', where,
                         f'{oid} belongs to principal {op.get("principal")}, not {pid}')
            if agent:
                reason = self.privileged_operation(op)
                if reason:
                    self.add('AGENT_PRIVILEGED_GRANT', where, f'{oid}: {reason}')
        for cid in caps:
            cap = self.capabilities.get(cid)
            if cap is None:
                self.add('GRANT_MISSING', where, f'capability {cid!r} is not defined')
                continue
            if agent and (cid == CODE_MERGE or cap.get('authority') in csi.PRIVILEGED_AUTHORITIES):
                self.add('AGENT_PRIVILEGED_GRANT', where,
                         f'{cid}: a capability of {cap.get("authority")} authority')
        for cid in creds:
            cred = self.credentials.get(cid)
            if cred is None:
                self.add('GRANT_MISSING', where, f'credential {cid!r} is not in the inventory')
                continue
            if agent and cred.get('authority') in csi.PRIVILEGED_AUTHORITIES:
                self.add('AGENT_PRIVILEGED_GRANT', where,
                         f'{cid}: a credential of {cred.get("authority")} authority')
            if agent and cred.get('authority') == 'provider':
                self.add('PROVIDER_ROLE_TOKEN', where,
                         f'{cid}: a provider credential is never a role token')

        for cid in self.id_list(f'{where}.custodian_of', role.get('custodian_of', [])):
            cred = self.credentials.get(cid)
            if cred is None:
                self.add('GRANT_MISSING', where, f'custodian_of {cid!r} is not in the inventory')
            elif cred.get('manager') != pid:
                self.add('CUSTODY_MISMATCH', where,
                         f'{cid} is managed by {cred.get("manager")} in the inventory, not {pid}')
            if agent:
                self.add('AGENT_PRIVILEGED_GRANT', where,
                         f'an agent-controlled role is custodian of {cid}')

        denied = self.id_list(f'{where}.denied', role.get('denied', []))
        for did in denied:
            if did not in self.operations and did not in self.credentials \
                    and did not in self.capabilities:
                self.add('DANGLING_REF', where, f'denied id {did!r} does not exist')
            if did in granted:
                self.add('DENIAL_GRANTED', where, f'{did} is both granted and denied')
        if agent:
            missing = [d for d in AGENT_BASELINE_DENIALS if d not in denied]
            if missing:
                self.add('DENIAL_MISSING', where,
                         f'an agent-controlled role must deny {missing}')

        self.check_realization(where, role)
        self.check_issuance(where, role, creds)
        self.check_revocation(where, role, creds, agent)
        self.check_bootstrap(where, role.get('bootstrap'))
        self.check_status(where, role, self.findings)

    def privileged_operation(self, op):
        if op.get('owner_only') is True:
            return 'an Owner-only operation'
        principal = self.principals.get(op.get('principal'), {})
        if principal.get('kind') == 'executor' or any(
                self.credentials.get(c, {}).get('authority') == 'executor'
                for c in op.get('credentials', []) or []):
            return 'an executor operation'
        if op.get('id') == GITEA_ADMIN:
            return 'Gitea administration'
        if op.get('id', '').startswith(MANAGEMENT_PREFIX):
            return 'an Agent Server management operation'
        return None

    def check_realization(self, where, role):
        rows = role.get('realization', [])
        if not isinstance(rows, list):
            self.add('SCHEMA', where, 'realization must be a list')
            return
        for n, row in enumerate(rows):
            w = f'{where}.realization[{n}]'
            if not isinstance(row, dict):
                self.add('SCHEMA', w, 'must be an object')
                continue
            self.keys(w, row, REALIZATION_KEYS)
            self.text(w, row, 'mechanism')
            if not isinstance(row.get('verified'), bool):
                self.add('SCHEMA', w, 'verified must be true or false')
            evidence = self.check_links(w, row, 'evidence')
            if row.get('verified') is True and not evidence:
                self.add('REALIZATION_UNSUPPORTED', w, 'verified needs at least one evidence link')
            if not _in(row.get('verify_at'), self.plan):
                self.add('DANGLING_REF', w, f"verify_at {row.get('verify_at')!r} is not a plan leaf")

    def rows_by_credential(self, where, rows, name, keys):
        if not isinstance(rows, list):
            self.add('SCHEMA', where, f'{name} must be a list')
            return {}
        out = {}
        for n, row in enumerate(rows):
            w = f'{where}.{name}[{n}]'
            if not isinstance(row, dict):
                self.add('SCHEMA', w, 'must be an object')
                continue
            self.keys(w, row, keys)
            cid = row.get('credential')
            if not isinstance(cid, str):
                self.add('SCHEMA', w, 'credential must be an id')
                continue
            if cid in out:
                self.add('CONTRACT_MISSING', w, f'{cid} has two {name} rows')
            out[cid] = row
        return out

    def check_issuance(self, where, role, creds):
        rows = self.rows_by_credential(where, role.get('issuance', []), 'issuance', ISSUANCE_KEYS)
        if set(rows) != set(creds):
            self.add('CONTRACT_MISSING', where, 'issuance must have exactly one row per granted '
                     f'credential: missing {sorted(set(creds) - set(rows))}, extra '
                     f'{sorted(set(rows) - set(creds), key=str)}')
        for cid, row in rows.items():
            w = f'{where}.issuance.{cid}'
            self.text(w, row, 'delivery')
            cred = self.credentials.get(cid)
            issuer = row.get('issuer')
            if cred is not None and issuer != cred.get('issuer'):
                self.add('ISSUER_MISMATCH', w, f'issuer {issuer!r}, but the inventory names '
                         f"{cred.get('issuer')!r}")
            delivered = row.get('delivered_by')
            if delivered is not None and not _in(delivered, self.roles):
                self.add('DANGLING_REF', w, f'delivered_by {delivered!r} is not a role')
            for pid in (issuer, self.role_principal(delivered)):
                if _in(pid, self.principals) and self.principals[pid].get('kind') == 'executor':
                    self.add('EXECUTOR_ISSUES', w, 'the executor issues and delivers nothing')

    def check_revocation(self, where, role, creds, agent):
        rows = self.rows_by_credential(where, role.get('revocation', []), 'revocation',
                                       REVOCATION_KEYS)
        if set(rows) != set(creds):
            self.add('CONTRACT_MISSING', where, 'revocation must have exactly one row per granted '
                     f'credential: missing {sorted(set(creds) - set(rows))}, extra '
                     f'{sorted(set(rows) - set(creds), key=str)}')
        for cid, row in rows.items():
            w = f'{where}.revocation.{cid}'
            self.text(w, row, 'method')
            triggers = row.get('triggers')
            if not isinstance(triggers, list) or not triggers \
                    or any(t not in TRIGGERS for t in triggers):
                self.add('TRIGGER_INVALID', w, f'triggers must be a non-empty subset of {TRIGGERS}')
                triggers = []
            required = REQUIRED_TRIGGERS + (AGENT_REQUIRED_TRIGGERS if agent else ())
            missing = [t for t in required if t not in triggers]
            if missing:
                self.add('TRIGGER_INVALID', w, f'triggers must include {missing}')
            cred = self.credentials.get(cid) or {}
            store = row.get('receipt_store', 'integration-store')
            if store not in RECEIPT_STORES:
                self.add('SCHEMA', w, f'receipt_store must be one of {RECEIPT_STORES}')
            elif store == 'effects-store' and cred.get('authority') not in ('executor',):
                self.add('RECEIPT_STORE', w, 'only an executor effect leaves its receipt in the '
                         'effects store (decision 0004, point 1): an executor credential\'s '
                         'rotation')
            issuer = cred.get('issuer')
            revoker = row.get('revoker')
            if not _in(revoker, self.roles):
                self.add('DANGLING_REF', w, f'revoker {revoker!r} is not a role')
            elif issuer in self.principals and self.role_principal(revoker) != issuer:
                self.add('REVOKER_NOT_ISSUER', w, f'the revoker is the issuer\'s role ({issuer}), '
                         f'not {revoker}')
            refs = row.get('findings', [])
            if not isinstance(refs, list):
                self.add('SCHEMA', w, 'findings must be a list')
                refs = []
            for ref in refs:
                if not _in(ref, self.findings):
                    self.add('DANGLING_REF', w, f'finding {ref!r} does not exist')
            rotation = row.get('rotation_owner')
            if rotation is None:
                if not refs:
                    self.add('ROTATION_UNDECIDED', w, 'a null rotation owner needs a finding')
                rotation_pid = None
            elif not _in(rotation, self.roles):
                self.add('DANGLING_REF', w, f'rotation_owner {rotation!r} is not a role')
                continue
            else:
                rotation_pid = self.role_principal(rotation)
            if cred and rotation_pid != cred.get('rotation_revocation_owner'):
                self.add('ROTATION_MISMATCH', w, f'rotation owner {rotation_pid!r}, but the '
                         f"inventory names {cred.get('rotation_revocation_owner')!r}")

    def check_bootstrap(self, where, boot):
        w = f'{where}.bootstrap'
        if not isinstance(boot, dict):
            self.add('SCHEMA', w, 'bootstrap must be an object')
            return
        self.keys(w, boot, BOOTSTRAP_KEYS)
        self.text(w, boot, 'note')
        performer = boot.get('observed_performer')
        if performer is not None and not _in(performer, self.principals):
            self.add('DANGLING_REF', w, f'observed_performer {performer!r} is not a principal')
        if not self.check_links(w, boot, 'evidence'):
            self.add('STATUS_UNSUPPORTED', w, 'bootstrap needs at least one evidence link')

    def check_non_roles(self):
        for n, row in enumerate(self.rows('non_roles')):
            where = f'non_roles[{n}]'
            if not isinstance(row, dict):
                self.add('SCHEMA', where, 'must be an object')
                continue
            where = f"non_roles.{row.get('id')}"
            self.keys(where, row, NON_ROLE_KEYS)
            pid = row.get('principal')
            principal = self.principals.get(pid) if isinstance(pid, str) else None
            if principal is None:
                self.add('ROLE_PRINCIPAL_MISSING', where, f'principal {pid!r} does not exist')
            if row.get('grants') != []:
                self.add('GRANT_NOT_ISOLATED', where, 'a non-role row carries no grants: '
                         f'{pid} is not an independently isolated principal')
            reach = row.get('inherits_reach_of')
            if not _in(reach, self.principals):
                self.add('DANGLING_REF', where, f'inherits_reach_of {reach!r} is not a principal')
            elif principal is not None and principal.get('shares_os_identity_with') != reach:
                self.add('SCHEMA', where, f'{pid} does not share the OS identity of {reach}')
            self.check_sunset(where, row, reach)
            self.check_status(where, row, self.findings)

    def check_sunset(self, where, row, reach):
        entries = row.get('sunset')
        if not isinstance(entries, list) or not entries:
            self.add('SUNSET_INCOMPLETE', where, 'the sunset map must be a non-empty list')
            entries = []
        covered = set()
        for n, entry in enumerate(entries):
            w = f'{where}.sunset[{n}]'
            if not isinstance(entry, dict):
                self.add('SCHEMA', w, 'must be an object')
                continue
            self.keys(w, entry, SUNSET_KEYS)
            self.text(w, entry, 'scope')
            for oid in self.id_list(f'{w}.operations', entry.get('operations', [])):
                if oid not in self.operations:
                    self.add('DANGLING_REF', w, f'operation {oid!r} is not in the inventory')
                covered.add(oid)
            at = entry.get('at')
            if at is None:
                self.text(w, entry, 'gap')
            elif not _in(at, self.plan):
                self.add('DANGLING_REF', w, f'at {at!r} is not a plan leaf')
        for oid, op in self.operations.items():
            principal = self.principals.get(op.get('principal'), {})
            planned = op.get('status') == 'planned' or principal.get('owner_authority') is not True
            if op.get('observed_performer') == reach and planned and oid not in covered:
                self.add('SUNSET_INCOMPLETE', where, f'{oid} is performed by {reach} today and '
                         f'planned for {op.get("principal")}: the sunset map must name its leaf')

    def check_coverage(self):
        ops = set()
        creds = set()
        for role in self.roles.values():
            grants = role.get('grants') if isinstance(role.get('grants'), dict) else {}
            ops.update(x for x in _list(grants.get('operations')) if isinstance(x, str))
            creds.update(x for x in _list(grants.get('credentials')) if isinstance(x, str))
        for oid in self.operations:
            if oid not in ops:
                self.add('COVERAGE', f'operations.{oid}', 'no role is granted this operation')
        for cid in self.credentials:
            if cid not in creds:
                self.add('COVERAGE', f'credentials.{cid}', 'no role is granted this credential')

    def check_policy_readme(self):
        if self.readme is None:
            return
        if csi.MACHINE_PATH.search(self.readme):
            self.add('MACHINE_PATH', 'readme', 'a machine-specific path must not be published')
        for ident in [*self.roles, *self.capabilities]:
            if f'`{ident}`' not in self.readme:
                self.add('README_MISSING', ident, 'the README does not name this id (as `id`)')
        block = generated_block(self.readme)
        if block is None:
            self.add('README_STALE', 'readme', 'the generated tables are missing their markers')
        elif block.strip() != render(self.policy, self.inv).strip():
            self.add('README_STALE', 'readme', 'the generated tables differ from --render; '
                     're-render them from the matrix')


def generated_block(text):
    start = text.find(GENERATED_BEGIN)
    end = text.find(GENERATED_END)
    if start < 0 or end < start:
        return None
    return text[start + len(GENERATED_BEGIN):end]


def _list(value):
    return value if isinstance(value, list) else []


def _dict(value):
    return value if isinstance(value, dict) else {}


def _str(value):
    return value if isinstance(value, str) else ''


def _ids(values):
    values = [str(v) for v in _list(values)]
    return ', '.join(f'`{v}`' for v in values) if values else '-'


def _cell(value):
    return str(value).replace('|', '\\|').replace('\n', ' ')


def _dicts(value):
    return [v for v in _list(value) if isinstance(v, dict)]


def render(policy, inventory):
    """The README's generated tables, rendered from the matrix and the inventory."""
    policy, inventory = _dict(policy), _dict(inventory)
    roles = _dicts(policy.get('roles'))
    principals = {p.get('id'): p for p in _dicts(inventory.get('principals'))
                  if isinstance(p.get('id'), str)}
    ops = {o.get('id'): o for o in _dicts(inventory.get('operations'))
           if isinstance(o.get('id'), str)}
    out = ['', '### Roles and grants', '',
           '| Role | Principal | Agent-controlled | Operations | Capabilities | Credentials | Status |',
           '|---|---|---|---|---|---|---|']
    for r in roles:
        g = _dict(r.get('grants'))
        out.append(f"| `{r.get('id')}` {_cell(_str(r.get('name')))} | `{r.get('principal')}` | "
                   f"{'yes' if r.get('agent_controlled') is True else 'no'} | "
                   f"{_ids(g.get('operations'))} | {_ids(g.get('capabilities'))} | "
                   f"{_ids(g.get('credentials'))} | {r.get('status')} |")
    out += ['', '### Denials', '',
            '| Role | Denied (operations, capabilities, credentials) |', '|---|---|']
    for r in roles:
        if _list(r.get('denied')):
            out.append(f"| `{r.get('id')}` | {_ids(r.get('denied'))} |")
    out += ['', '### Capabilities', '',
            '| Capability | Authority | Granted to | Delegation | Status |', '|---|---|---|---|---|']
    for c in _dicts(policy.get('capabilities')):
        holders = [r.get('id') for r in roles
                   if c.get('id') in _list(_dict(r.get('grants')).get('capabilities'))]
        d = _dict(c.get('delegation'))
        delegation = f"{_cell(_str(d.get('to')))} ({d.get('by')})" if d else '-'
        out.append(f"| `{c.get('id')}` {_cell(_str(c.get('name')))}: "
                   f"{_cell(_str(c.get('description')))} | {c.get('authority')} | "
                   f"{_ids(holders) if holders else 'no role'} | {delegation} | {c.get('status')} |")
    out += ['', '### Issuance and revocation', '',
            '| Credential | Role | Issuer | Delivered by | Delivery | Revoker | Revocation | '
            'Triggers | Rotation owner |', '|---|---|---|---|---|---|---|---|---|']
    for r in roles:
        issuance = {i.get('credential'): i for i in _dicts(r.get('issuance'))
                    if isinstance(i.get('credential'), str)}
        for v in _dicts(r.get('revocation')):
            cred = v.get('credential')
            i = issuance.get(cred, {}) if isinstance(cred, str) else {}
            rotation = f"`{v.get('rotation_owner')}`" if v.get('rotation_owner') else 'undecided'
            store = v.get('receipt_store')
            method = _cell(_str(v.get('method'))) + (f' Receipt: {store}.' if store else '')
            delivered = i.get('delivered_by')
            out.append(f"| `{cred}` | `{r.get('id')}` | `{i.get('issuer')}` | "
                       f"{_ids([delivered] if delivered else [])} | "
                       f"{_cell(_str(i.get('delivery')))} | `{v.get('revoker')}` | {method} | "
                       f"{', '.join(str(x) for x in _list(v.get('triggers')))} | {rotation} |")
    out += ['', '### Realization', '',
            '| Role | Mechanism | Verified | Verify at | Evidence |', '|---|---|---|---|---|']
    for r in roles:
        for m in _dicts(r.get('realization')):
            note = f" Note: {_str(m.get('notes'))}" if m.get('notes') else ''
            out.append(f"| `{r.get('id')}` | {_cell(_str(m.get('mechanism')) + note)} | "
                       f"{'yes' if m.get('verified') is True else 'no'} | {m.get('verify_at')} | "
                       f"{_ids(m.get('evidence'))} |")
    out += ['', '### Target and bootstrap', '',
            '| Role | Target | Bootstrap: observed performer | Bootstrap: note |',
            '|---|---|---|---|']
    for r in roles:
        b = _dict(r.get('bootstrap'))
        performer = b.get('observed_performer')
        target = _cell(_str(r.get('target')))
        if _list(r.get('custodian_of')):
            target += f" Custodian of {_ids(r.get('custodian_of'))}."
        for invariant in _list(r.get('invariants')):
            target += f' Invariant: {_cell(invariant)}'
        out.append(f"| `{r.get('id')}` | {target} | "
                   f"{f'`{performer}`' if performer else 'none'} | {_cell(_str(b.get('note')))} |")
    out += ['', '### Non-roles and the sunset map', '']
    for n in _dicts(policy.get('non_roles')):
        pid = n.get('principal')
        p = principals.get(pid, {}) if isinstance(pid, str) else {}
        out.append(f"`{n.get('id')}` (principal `{pid}`, independently isolated: "
                   f"{'yes' if p.get('independently_isolated') is True else 'no'}): no grants; "
                   f"inherits the reach of `{n.get('inherits_reach_of')}`; findings "
                   f"{_ids(n.get('findings'))}.")
        out += ['', '| Operations | Move at | To (inventory principal) | Scope |',
                '|---|---|---|---|']
        for s in _dicts(n.get('sunset')):
            names = [o for o in _list(s.get('operations')) if isinstance(o, str)]
            to = sorted({ops.get(o, {}).get('principal') or '?' for o in names})
            at = s.get('at') or f"none ({_cell(_str(s.get('gap')))})"
            out.append(f"| {_ids(names)} | {at} | {_ids(to)} | {_cell(_str(s.get('scope')))} |")
    out.append('')
    return '\n'.join(out)


def check(policy, inventory, root, readme_text=None):
    """Return the problems found in ``policy`` against ``inventory`` (parsed JSON values)."""
    return Checker(policy, inventory, root, readme_text).run()


def summary(policy):
    roles = [r for r in policy.get('roles', []) if isinstance(r, dict)]
    agents = [r for r in roles if r.get('agent_controlled') is True]
    rows = [m for r in roles for m in r.get('realization', []) if isinstance(m, dict)]
    return (f"{len(roles)} roles ({len(agents)} agent-controlled: "
            f"{', '.join(r.get('id') for r in agents)}), "
            f"{len(policy.get('capabilities', []))} capabilities, "
            f"{len(policy.get('non_roles', []))} non-role row(s), "
            f"{sum(len(r.get('revocation', [])) for r in roles)} revocation rows, "
            f"{len(rows)} realization rows ({sum(1 for m in rows if m.get('verified') is True)} "
            'verified)')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--root', default='.', help='repository root (default: .)')
    parser.add_argument('--policy', help='matrix file (default: <root>/policy/role-tokens.json)')
    parser.add_argument('--inventory', help='security inventory (default: the matrix\'s '
                        '"inventory" entry under the root)')
    parser.add_argument('--readme', help='README naming every role (default: the matrix\'s '
                        '"readme" entry under the root)')
    parser.add_argument('--list', action='store_true',
                        help='also print each role with its principal and grant counts')
    parser.add_argument('--render', action='store_true',
                        help='print the README\'s generated tables and exit')
    args = parser.parse_args(argv)
    root = Path(args.root)
    path = Path(args.policy) if args.policy else root / DEFAULT_POLICY
    try:
        policy = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        print(f'ERROR: cannot read {path}: {exc}', file=sys.stderr)
        return 2
    inv_rel = policy.get('inventory') if isinstance(policy, dict) else None
    inv_path = Path(args.inventory) if args.inventory else root / (inv_rel or DEFAULT_INVENTORY)
    try:
        inventory = json.loads(inv_path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        print(f'ERROR: cannot read {inv_path}: {exc}', file=sys.stderr)
        return 2
    if not isinstance(inventory, dict):
        print(f'ERROR: {inv_path} is not a JSON object', file=sys.stderr)
        return 2
    if args.render:
        sys.stdout.write(render(policy, inventory))
        return 0
    readme_rel = args.readme or (policy.get('readme') if isinstance(policy, dict) else None)
    readme_text = None
    if readme_rel:
        readme_path = Path(args.readme) if args.readme else root / readme_rel
        try:
            readme_text = readme_path.read_text(encoding='utf-8')
        except OSError as exc:
            print(f'ERROR: cannot read {readme_path}: {exc}', file=sys.stderr)
            return 2
    problems = check(policy, inventory, root, readme_text)
    if args.list and isinstance(policy, dict):
        for r in policy.get('roles', []):
            if isinstance(r, dict):
                g = _dict(r.get('grants'))
                counts = ', '.join(f'{k} {len(g.get(k) or [])}' for k in GRANT_KEYS)
                flag = ' [agent-controlled]' if r.get('agent_controlled') else ''
                print(f"{r.get('id')}: {r.get('principal')} ({counts}; denied "
                      f"{len(r.get('denied') or [])}; {r.get('status')}){flag}")
    for problem in problems:
        print(f'FAIL {problem}')
    if problems:
        print(f'FAIL {path.as_posix()}: {len(problems)} problem(s)')
        return 1
    print(f'PASS {path.as_posix()}: {summary(policy)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
