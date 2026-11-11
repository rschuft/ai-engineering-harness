"""Tests for tools/check_role_tokens.py and policy/role-tokens.json (plan leaf S-01.2.1).

Run from the repository root:  python -I -B -m unittest discover -s tools/tests -v

The committed matrix must pass against the committed inventory. Each negative case
mutates an in-memory copy of the matrix (or of the inventory, or a copy in a temporary
directory for the command line) and must fail with the expected code. The checkout is
only read.
"""
from pathlib import Path
import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest

CATEGORY = 'unit'

REPO = Path(__file__).resolve().parents[2]
CHECKER = REPO / 'tools' / 'check_role_tokens.py'
POLICY_PATH = REPO / 'policy' / 'role-tokens.json'
README_PATH = REPO / 'policy' / 'README.md'
INVENTORY_PATH = REPO / 'security' / 'inventory.json'

_spec = importlib.util.spec_from_file_location('check_role_tokens', CHECKER)
crt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(crt)

POLICY = json.loads(POLICY_PATH.read_text(encoding='utf-8'))
INVENTORY = json.loads(INVENTORY_PATH.read_text(encoding='utf-8'))
README = README_PATH.read_text(encoding='utf-8')
AGENT_ROLES = ('planner', 'builder', 'reviewer', 'ci-job')
# (role, mechanism prefix) -> the open leaf an unverified realization was re-pointed to by the
# plan reconciliation of 2026-11-08 (evidence/plan-reconciliation-2026-11-08.md)
REPOINTED = {
    ('owner', 'A separate Gitea Owner account'): 'P-04.2',
    # Owner decision OA-16 (evidence/P-04.2-protection-verifier.md): the recorder's protection auditor
    ('authorization-recorder', 'The protection auditor'): 'P-04.2',
    ('gitea-site-admin', 'Issues Gitea identities'): 'Q-02.2.1',
    ('reviewer', 'A dedicated Gitea bot account'): 'D-01.2',
    ('ci-job', 'The Gitea Actions job token'): 'Q-02.3.1',
    ('ci-job', 'A disposable container or VM'): 'Q-02.2.2',
    ('ci-runner-service', "The runner's registration secret"): 'Q-02.3.2',
    ('management-dispatcher', 'The sole holder'): 'E-01.3.3',
    ('management-dispatcher', 'Custodian of the standing bot credentials'): 'E-01.3.3',
    ('inference-broker', 'The host-side broker'): 'S-03.2',
    ('release-job-environment', 'Not decided'): 'Q-02.4',
}


def fresh():
    return copy.deepcopy(POLICY)


def fresh_inventory():
    return copy.deepcopy(INVENTORY)


def role(pol, ident):
    for item in pol['roles']:
        if item['id'] == ident:
            return item
    raise AssertionError(f'fixture has no role {ident!r}')


def row(rows, cred):
    for item in rows:
        if item['credential'] == cred:
            return item
    raise AssertionError(f'fixture has no row for {cred!r}')


def inv_entry(inv, collection, ident):
    for item in inv[collection]:
        if item['id'] == ident:
            return item
    raise AssertionError(f'inventory has no {collection} entry {ident!r}')


def codes(pol, inv=None, readme=README):
    problems = crt.check(pol, INVENTORY if inv is None else inv, REPO, readme)
    return {p.code for p in problems}, problems


def run_cli(*args):
    return subprocess.run([sys.executable, '-I', '-B', str(CHECKER), *map(str, args)],
                          capture_output=True, text=True, encoding='utf-8', cwd=REPO)


class CommittedMatrix(unittest.TestCase):
    category = 'contract'

    def test_matrix_passes(self):
        found, problems = codes(fresh())
        self.assertEqual(problems, [], '\n'.join(map(str, problems)))

    def test_no_agent_reviewer_or_ci_role_has_owner_or_privileged_effect_capability(self):
        """The leaf's acceptance, read straight from the data, independently of the checker."""
        principals = {p['id']: p for p in INVENTORY['principals']}
        operations = {o['id']: o for o in INVENTORY['operations']}
        credentials = {c['id']: c for c in INVENTORY['credentials']}
        capabilities = {c['id']: c for c in POLICY['capabilities']}
        agents = [r for r in POLICY['roles'] if principals[r['principal']]['agent_controlled']]
        self.assertEqual(sorted(r['id'] for r in agents), sorted(AGENT_ROLES))
        privileged = set(crt.csi.PRIVILEGED_AUTHORITIES)
        for r in agents:
            with self.subTest(role=r['id']):
                for oid in r['grants']['operations']:
                    op = operations[oid]
                    self.assertFalse(op['owner_only'], oid)
                    self.assertEqual(op['principal'], r['principal'], oid)
                    self.assertNotEqual(principals[op['principal']]['kind'], 'executor', oid)
                    self.assertFalse(oid.startswith('op-as-') or oid == 'op-gitea-administration')
                for cid in r['grants']['credentials']:
                    self.assertNotIn(credentials[cid]['authority'], privileged | {'provider'}, cid)
                for cid in r['grants']['capabilities']:
                    self.assertNotIn(capabilities[cid]['authority'], privileged, cid)
                self.assertNotIn('cap-code-merge-integration', r['grants']['capabilities'])
                self.assertFalse(r.get('custodian_of'))

    def test_realizations_as_s_01_3_2_left_them(self):
        # S-01.2.2, S-01.3.1 and S-01.3.2 verified only what their evidence shows; every other
        # row stays unverified and says why.
        rows = [(r['id'], m) for r in POLICY['roles'] for m in r['realization']]
        self.assertTrue(rows)
        self.assertEqual(sorted(rid for rid, m in rows if m['verified'] is True),
                         ['authorization-verifier', 'builder', 'builder', 'builder',
                          'gitea-site-admin', 'management-dispatcher', 'planner', 'reviewer'])
        for rid, m in rows:
            admission = rid == 'management-dispatcher' and m['mechanism'].startswith('Admission')
            job = m['mechanism'].startswith('The job environment')
            ci_job = rid == 'ci-job' and m['mechanism'].startswith('The runner containment')
            if m['verified'] is True:
                self.assertIn('evidence/S-01.3.1-management-api-admission.md' if admission else
                              'evidence/S-01.3.2-job-daemon-and-management-access.md' if job else
                              'evidence/S-01.2.2-segregated-credentials.md', m['evidence'])
            else:
                self.assertIs(m['verified'], False, m['mechanism'])
                self.assertTrue(m.get('notes'), m['mechanism'])
            carried = {'privileged-executor': 'G-04.2.1'}
            if rid == 'owner' and m['mechanism'].startswith('Code merges'):
                carried['owner'] = 'D-01.2'
            if rid == 'management-dispatcher' and m['mechanism'].startswith('The sole network path'):
                carried[rid] = 'E-01.3.2'              # decision 0013 (S-01.4)
            # unverified rows re-pointed to their decided owners by the plan reconciliation of
            # 2026-11-08; the deferred planner and integration-service rows keep S-01.2.2
            for (r_id, prefix), leaf in REPOINTED.items():
                if rid == r_id and m['mechanism'].startswith(prefix):
                    self.assertIs(m['verified'], False, m['mechanism'])
                    carried[rid] = leaf
            if admission:
                carried[rid] = 'S-01.3.1'
            if job:
                carried[rid] = 'S-01.3.2'
                self.assertIn(rid, ('builder', 'reviewer'))
            if ci_job:
                carried[rid] = 'Q-02.2.2'
                self.assertIs(m['verified'], False)
            self.assertEqual(m['verify_at'], carried.get(rid, 'S-01.2.2'), m['mechanism'])

    def test_every_role_binds_to_one_inventory_principal(self):
        principals = {p['id'] for p in INVENTORY['principals']}
        for r in POLICY['roles']:
            self.assertIsInstance(r['principal'], str, r['id'])
            self.assertIn(r['principal'], principals, r['id'])
        self.assertEqual(role(POLICY, 'planner')['principal'], 'engineering-agent')
        self.assertEqual(role(POLICY, 'builder')['principal'], 'engineering-agent')

    def test_bootstrap_agents_are_a_non_role_without_grants(self):
        self.assertNotIn('bootstrap-host-agents', {r['principal'] for r in POLICY['roles']})
        (non_role,) = POLICY['non_roles']
        self.assertEqual(non_role['principal'], 'bootstrap-host-agents')
        self.assertEqual(non_role['grants'], [])
        self.assertEqual(non_role['inherits_reach_of'], 'owner-os-account')
        self.assertIn('fd-bootstrap-shared-identity', non_role['findings'])

    def test_sunset_map(self):
        (non_role,) = POLICY['non_roles']
        at = {op: s['at'] for s in non_role['sunset'] for op in s['operations']}
        # moved to the dispatcher at E-01.3.3 by the plan reconciliation of 2026-11-08
        self.assertEqual(at['op-as-conversation-create'], 'E-01.3.3')
        self.assertEqual(at['op-as-runtime-stop'], 'E-01.3.3')
        self.assertEqual(at['op-effect-apply'], 'G-04.2.1')
        self.assertEqual(at['op-effect-store-custody'], 'G-04.2.1')
        self.assertIsNone(at['op-gitea-administration'])

    def test_named_denials(self):
        for rid in ('planner', 'builder'):
            denied = set(role(POLICY, rid)['denied'])
            self.assertTrue({'op-protected-merge', 'cap-code-merge-integration',
                             'cap-protected-ref-push', 'op-gitea-administration',
                             'cap-work-status-mutation', 'op-effect-apply',
                             'cred-agent-server-session-key', 'cred-moby-docker-group'} <= denied, rid)
        self.assertIn('cap-push-proposal-branch', role(POLICY, 'reviewer')['denied'])
        ci = set(role(POLICY, 'ci-job')['denied'])
        self.assertTrue({'op-release-signing-deploy', 'cred-runner-registration',
                         'cred-gitea-owner-account', 'cred-moby-docker-group'} <= ci)

    def test_release_principal_stays_undecided(self):
        release = role(POLICY, 'release-job-environment')
        self.assertEqual(release['status'], 'unknown')
        self.assertEqual(release['grants']['credentials'], [])
        self.assertIn('fd-release-job-principal', release['findings'])

    def test_inventory_edits(self):
        creds = {c['id']: c for c in INVENTORY['credentials']}
        self.assertIn('cred-gitea-bot-planner', creds)
        # S-01.4 (decision 0013): the Owner UI's access splits into two planned credentials
        self.assertNotIn('cred-owner-ui-access', creds)
        owner = role(POLICY, 'owner')['grants']['credentials']
        self.assertIn('cred-owner-ui-session', owner)
        self.assertIn('cred-conversation-runtime-access', owner)
        self.assertEqual(creds['cred-conversation-runtime-access']['issuer'], 'management-dispatcher')
        self.assertNotIn(creds['cred-conversation-runtime-access']['authority'],
                         ('owner', 'admin', 'executor', 'management'))
        self.assertEqual(creds['cred-gitea-bot-planner']['holder'], 'engineering-agent')
        self.assertTrue(all(c['rotation_revocation_owner'] for c in creds.values()))
        findings = {f['id']: f for f in INVENTORY['findings']}
        self.assertNotIn('fd-rotation-undecided', findings)
        self.assertIn('Q-02.4', findings['fd-release-job-principal']['carried_to'])

    def test_cli_passes_and_lists(self):
        result = run_cli('--list')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS policy/role-tokens.json', result.stdout)
        self.assertIn('builder: engineering-agent', result.stdout)

    def test_cli_render_matches_the_readme(self):
        result = run_cli('--render')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(crt.generated_block(README).strip(), result.stdout.strip())

    def test_cli_fails_on_a_mutated_copy(self):
        pol = fresh()
        role(pol, 'ci-job')['grants']['operations'].append('op-effect-apply')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'role-tokens.json'
            path.write_text(json.dumps(pol), encoding='utf-8')
            result = run_cli('--policy', path)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('AGENT_PRIVILEGED_GRANT', result.stdout)

    def test_cli_cannot_run_without_a_matrix(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_cli('--policy', Path(tmp) / 'missing.json')
        self.assertEqual(result.returncode, 2)


class Acceptance(unittest.TestCase):
    """The leaf's named mutation cases, and the branches behind them."""

    def assert_code(self, code, pol, inv=None, where=None, readme=README):
        found, problems = codes(pol, inv, readme)
        self.assertIn(code, found, '\n'.join(map(str, problems)))
        if where:
            self.assertTrue(any(p.code == code and where in p.where for p in problems),
                            '\n'.join(map(str, problems)))

    def test_protected_merge_granted_to_builder_fails(self):
        pol = fresh()
        role(pol, 'builder')['grants']['operations'].append('op-protected-merge')
        self.assert_code('AGENT_PRIVILEGED_GRANT', pol, where='roles.builder')

    def test_session_key_granted_to_reviewer_fails(self):
        pol = fresh()
        role(pol, 'reviewer')['grants']['credentials'].append('cred-agent-server-session-key')
        self.assert_code('AGENT_PRIVILEGED_GRANT', pol, where='roles.reviewer')

    def test_effect_apply_granted_to_ci_job_fails(self):
        pol = fresh()
        role(pol, 'ci-job')['grants']['operations'].append('op-effect-apply')
        self.assert_code('AGENT_PRIVILEGED_GRANT', pol, where='roles.ci-job')

    def test_any_grant_to_bootstrap_agents_fails(self):
        pol = fresh()
        pol['non_roles'][0]['grants'] = ['op-guest-exec']
        self.assert_code('GRANT_NOT_ISOLATED', pol)

    def test_a_role_on_the_bootstrap_agents_with_a_grant_fails(self):
        pol = fresh()
        extra = copy.deepcopy(role(pol, 'guest-login-agent'))
        extra.update(id='bootstrap-operator', principal='bootstrap-host-agents',
                     agent_controlled=True)
        extra['grants']['operations'] = ['op-guest-exec']
        pol['roles'].append(extra)
        self.assert_code('GRANT_NOT_ISOLATED', pol, where='roles.bootstrap-operator')

    def test_code_merge_granted_to_planner_fails(self):
        pol = fresh()
        role(pol, 'planner')['grants']['capabilities'].append('cap-code-merge-integration')
        self.assert_code('AGENT_PRIVILEGED_GRANT', pol, where='roles.planner')

    def test_code_merge_stays_denied_to_agents_even_if_relabelled_scoped(self):
        pol = fresh()
        for cap in pol['capabilities']:
            if cap['id'] == 'cap-code-merge-integration':
                cap['authority'] = 'scoped'
        role(pol, 'planner')['grants']['capabilities'].append('cap-code-merge-integration')
        self.assert_code('AGENT_PRIVILEGED_GRANT', pol, where='roles.planner')

    def test_role_on_a_nonexistent_principal_fails(self):
        pol = fresh()
        role(pol, 'reviewer')['principal'] = 'review-bot'
        self.assert_code('ROLE_PRINCIPAL_MISSING', pol, where='roles.reviewer')

    def test_operation_of_another_principal_fails(self):
        pol = fresh()
        role(pol, 'builder')['grants']['operations'].append('op-submit-review')
        self.assert_code('GRANT_PRINCIPAL_MISMATCH', pol, where='roles.builder')

    def test_null_rotation_owner_without_a_finding_fails(self):
        pol = fresh()
        r = row(role(pol, 'builder')['revocation'], 'cred-gitea-bot-builder')
        r['rotation_owner'] = None
        r.pop('findings')
        self.assert_code('ROTATION_UNDECIDED', pol)

    def test_verified_realization_without_evidence_fails(self):
        pol = fresh()
        m = role(pol, 'builder')['realization'][0]
        m['verified'] = True
        m.pop('evidence', None)
        self.assert_code('REALIZATION_UNSUPPORTED', pol)

    def test_verified_realization_with_evidence_passes_that_rule(self):
        pol = fresh()
        m = role(pol, 'builder')['realization'][0]
        m['verified'] = True
        m['evidence'] = ['evidence/F-04.2-conversation-lifecycle.md']
        found, _ = codes(pol)
        self.assertNotIn('REALIZATION_UNSUPPORTED', found)

    def test_sunset_map_missing_conversation_create_fails(self):
        pol = fresh()
        pol['non_roles'][0]['sunset'][0]['operations'].remove('op-as-conversation-create')
        self.assert_code('SUNSET_INCOMPLETE', pol)

    def test_drive_letter_path_fails(self):
        for text in ('C:\\Users\\you\\state', 'D:/guest-state/instances', '\\\\server\\share',
                     '%USERPROFILE%\\.ssh'):
            with self.subTest(text=text):
                pol = fresh()
                role(pol, 'owner')['target'] = text
                self.assert_code('MACHINE_PATH', pol)

    def test_machine_path_in_the_readme_fails(self):
        self.assert_code('MACHINE_PATH', fresh(), readme=README + '\nSee D:\\state\\x.\n')


class AgentGrants(unittest.TestCase):
    """Each branch of AGENT_PRIVILEGED_GRANT fires on its own, even when the operation is
    re-assigned to the agent's principal in the inventory (so no other rule fires)."""

    def assert_branch(self, oid, reason):
        inv = fresh_inventory()
        inv_entry(inv, 'operations', oid)['principal'] = 'engineering-agent'
        pol = fresh()
        role(pol, 'builder')['grants']['operations'].append(oid)
        _, problems = codes(pol, inv)
        hits = [p for p in problems if p.code == 'AGENT_PRIVILEGED_GRANT']
        self.assertTrue(any(reason in p.message for p in hits), '\n'.join(map(str, problems)))
        self.assertFalse([p for p in problems
                          if p.code == 'GRANT_PRINCIPAL_MISMATCH' and p.where == 'roles.builder'])

    def test_owner_only_operation(self):
        self.assert_branch('op-policy-change', 'Owner-only')

    def test_executor_operation(self):
        self.assert_branch('op-effect-receipt-write', 'executor operation')

    def test_gitea_administration(self):
        self.assert_branch('op-gitea-administration', 'Gitea administration')

    def test_management_operation(self):
        self.assert_branch('op-as-runtime-stop', 'management operation')

    def test_admin_credential_to_ci_job_fails(self):
        pol = fresh()
        role(pol, 'ci-job')['grants']['credentials'].append('cred-gitea-admin')
        _, problems = codes(pol)
        self.assertTrue(any(p.code == 'AGENT_PRIVILEGED_GRANT' and 'cred-gitea-admin' in p.message
                            for p in problems))

    def test_privileged_capability_to_reviewer_fails(self):
        pol = fresh()
        role(pol, 'reviewer')['grants']['capabilities'].append('cap-work-status-mutation')
        _, problems = codes(pol)
        self.assertTrue(any(p.code == 'AGENT_PRIVILEGED_GRANT' and 'cap-work-status' in p.message
                            for p in problems))

    def test_agent_custody_of_a_credential_fails(self):
        pol = fresh()
        role(pol, 'builder')['custodian_of'] = ['cred-gitea-bot-builder']
        found, _ = codes(pol)
        self.assertIn('AGENT_PRIVILEGED_GRANT', found)
        self.assertIn('CUSTODY_MISMATCH', found)

    def test_relabelling_an_agent_role_does_not_evade_the_rules(self):
        pol = fresh()
        builder = role(pol, 'builder')
        builder['agent_controlled'] = False
        builder['grants']['operations'].append('op-protected-merge')
        found, _ = codes(pol)
        self.assertIn('AGENT_CONTROLLED_MISMATCH', found)
        self.assertIn('AGENT_PRIVILEGED_GRANT', found)

    def test_provider_credential_is_never_a_role_token(self):
        pol = fresh()
        role(pol, 'builder')['grants']['credentials'].append('cred-llm-provider-key')
        self.assertIn('PROVIDER_ROLE_TOKEN', codes(pol)[0])


class Mapping(unittest.TestCase):
    def assert_code(self, code, pol, inv=None, readme=README):
        found, problems = codes(pol, inv, readme)
        self.assertIn(code, found, '\n'.join(map(str, problems)))

    def test_missing_ids_fail(self):
        for key, ident in (('operations', 'op-nothing'), ('capabilities', 'cap-nothing'),
                           ('credentials', 'cred-nothing')):
            with self.subTest(key=key):
                pol = fresh()
                role(pol, 'owner')['grants'][key].append(ident)
                self.assert_code('GRANT_MISSING', pol)

    def test_dangling_denial_fails(self):
        pol = fresh()
        role(pol, 'reviewer')['denied'].append('op-nothing')
        self.assert_code('DANGLING_REF', pol)

    def test_granted_and_denied_fails(self):
        pol = fresh()
        role(pol, 'builder')['denied'].append('cap-open-pr')
        self.assert_code('DENIAL_GRANTED', pol)

    def test_missing_baseline_denial_fails(self):
        pol = fresh()
        role(pol, 'reviewer')['denied'].remove('op-protected-merge')
        self.assert_code('DENIAL_MISSING', pol)

    def test_custody_of_a_credential_another_principal_manages_fails(self):
        pol = fresh()
        role(pol, 'management-dispatcher')['custodian_of'].append('cred-ci-job-token')
        self.assert_code('CUSTODY_MISMATCH', pol)

    def test_unmapped_operation_and_credential_fail(self):
        pol = fresh()
        broker = role(pol, 'inference-broker')
        broker['grants']['operations'] = []
        broker['grants']['credentials'] = []
        broker['issuance'] = []
        broker['revocation'] = []
        found, problems = codes(pol)
        self.assertIn('COVERAGE', found)
        where = {p.where for p in problems if p.code == 'COVERAGE'}
        self.assertEqual(where, {'operations.op-inference-call', 'credentials.cred-llm-provider-key'})

    def test_exclusion_flag_fails(self):
        for key in ('excluded_from_acceptance', 'exempt', 'waiver'):
            with self.subTest(key=key):
                pol = fresh()
                role(pol, 'ci-job')[key] = True
                self.assert_code('EXCLUSION_FLAG', pol)
        pol = fresh()
        pol['non_roles'][0]['skip_acceptance'] = True
        self.assert_code('EXCLUSION_FLAG', pol)

    def test_unknown_key_fails(self):
        pol = fresh()
        role(pol, 'ci-job')['scopes'] = ['repo']
        self.assert_code('SCHEMA', pol)

    def test_invalid_and_duplicate_ids_fail(self):
        pol = fresh()
        role(pol, 'reviewer')['id'] = 'Reviewer'
        self.assert_code('ID_INVALID', pol)
        pol = fresh()
        pol['capabilities'][1]['id'] = 'read-repositories'
        self.assert_code('ID_INVALID', pol)
        pol = fresh()
        pol['roles'].append(copy.deepcopy(role(pol, 'guest-login-agent')))
        self.assert_code('ID_DUPLICATE', pol)

    def test_grants_must_have_the_three_lists(self):
        pol = fresh()
        role(pol, 'owner')['grants'] = ['op-policy-change']
        self.assert_code('SCHEMA', pol)

    def test_capability_rules(self):
        pol = fresh()
        pol['capabilities'][0]['delegation']['by'] = 'D-99.9'
        self.assert_code('DANGLING_REF', pol)
        pol = fresh()
        pol['capabilities'][1]['authority'] = 'root'
        self.assert_code('SCHEMA', pol)
        pol = fresh()
        pol['capabilities'] = [c for c in pol['capabilities'] if c['id'] != 'cap-code-merge-integration']
        self.assert_code('SCHEMA', pol)


class Contract(unittest.TestCase):
    def assert_code(self, code, pol, inv=None):
        found, problems = codes(pol, inv)
        self.assertIn(code, found, '\n'.join(map(str, problems)))

    def test_missing_issuance_row_fails(self):
        pol = fresh()
        role(pol, 'builder')['issuance'].pop()
        self.assert_code('CONTRACT_MISSING', pol)

    def test_duplicate_revocation_row_fails(self):
        pol = fresh()
        rows = role(pol, 'reviewer')['revocation']
        rows.append(copy.deepcopy(rows[0]))
        self.assert_code('CONTRACT_MISSING', pol)

    def test_issuer_must_match_the_inventory(self):
        pol = fresh()
        row(role(pol, 'builder')['issuance'], 'cred-gitea-bot-builder')['issuer'] = 'owner'
        self.assert_code('ISSUER_MISMATCH', pol)

    def test_the_executor_issues_nothing(self):
        pol = fresh()
        row(role(pol, 'builder')['issuance'], 'cred-gitea-bot-builder')['delivered_by'] = \
            'privileged-executor'
        self.assert_code('EXECUTOR_ISSUES', pol)
        inv = fresh_inventory()
        inv_entry(inv, 'credentials', 'cred-verifier-read')['issuer'] = 'privileged-executor'
        pol = fresh()
        row(role(pol, 'authorization-verifier')['issuance'], 'cred-verifier-read')['issuer'] = \
            'privileged-executor'
        self.assert_code('EXECUTOR_ISSUES', pol, inv)

    def test_triggers_come_from_the_closed_set(self):
        pol = fresh()
        row(role(pol, 'owner')['revocation'], 'cred-uac-consent')['triggers'] = ['whenever']
        self.assert_code('TRIGGER_INVALID', pol)

    def test_every_row_includes_exposure_and_owner_direction(self):
        pol = fresh()
        row(role(pol, 'gitea-site-admin')['revocation'], 'cred-gitea-admin')['triggers'] = ['expiry']
        self.assert_code('TRIGGER_INVALID', pol)

    def test_agent_tokens_end_with_the_attempt(self):
        pol = fresh()
        r = row(role(pol, 'ci-job')['revocation'], 'cred-ci-job-token')
        r['triggers'].remove('attempt-end')
        self.assert_code('TRIGGER_INVALID', pol)

    def test_revoker_is_the_issuers_role(self):
        pol = fresh()
        row(role(pol, 'builder')['revocation'], 'cred-gitea-bot-builder')['revoker'] = \
            'management-dispatcher'
        self.assert_code('REVOKER_NOT_ISSUER', pol)

    def test_unknown_revoker_fails(self):
        pol = fresh()
        row(role(pol, 'builder')['revocation'], 'cred-gitea-bot-builder')['revoker'] = 'nobody'
        self.assert_code('DANGLING_REF', pol)

    def test_rotation_owner_must_match_the_inventory(self):
        pol = fresh()
        row(role(pol, 'builder')['revocation'], 'cred-gitea-bot-builder')['rotation_owner'] = \
            'gitea-site-admin'
        self.assert_code('ROTATION_MISMATCH', pol)
        inv = fresh_inventory()
        inv_entry(inv, 'credentials', 'cred-verifier-read')['rotation_revocation_owner'] = 'owner'
        self.assert_code('ROTATION_MISMATCH', fresh(), inv)

    def test_effects_store_receipt_only_for_an_executor_credential(self):
        pol = fresh()
        row(role(pol, 'builder')['revocation'], 'cred-gitea-bot-builder')['receipt_store'] = \
            'effects-store'
        self.assert_code('RECEIPT_STORE', pol)

    def test_contract_constants(self):
        pol = fresh()
        pol['revocation_contract']['new_dispatch'] = 'allowed-until-expiry'
        self.assert_code('SCHEMA', pol)
        pol = fresh()
        pol['revocation_contract']['receipt_store'] = 'effects-store'
        self.assert_code('SCHEMA', pol)
        pol = fresh()
        del pol['trigger_classes']['expiry']
        self.assert_code('SCHEMA', pol)


class StatusAndLinks(unittest.TestCase):
    def assert_code(self, code, pol, readme=README):
        found, problems = codes(pol, None, readme)
        self.assertIn(code, found, '\n'.join(map(str, problems)))

    def test_status_outside_the_closed_set_fails(self):
        pol = fresh()
        role(pol, 'builder')['status'] = 'enforced'
        self.assert_code('STATUS_INVALID', pol)

    def test_planned_without_sources_fails(self):
        pol = fresh()
        role(pol, 'builder')['sources'] = []
        self.assert_code('STATUS_UNSUPPORTED', pol)

    def test_unknown_without_a_finding_fails(self):
        pol = fresh()
        role(pol, 'release-job-environment')['findings'] = []
        self.assert_code('STATUS_UNSUPPORTED', pol)

    def test_bootstrap_needs_evidence(self):
        pol = fresh()
        role(pol, 'ci-job')['bootstrap']['evidence'] = []
        self.assert_code('STATUS_UNSUPPORTED', pol)

    def test_bootstrap_performer_must_exist(self):
        pol = fresh()
        role(pol, 'ci-job')['bootstrap']['observed_performer'] = 'someone'
        self.assert_code('DANGLING_REF', pol)

    def test_blueprint_anchor_must_exist(self):
        pol = fresh()
        role(pol, 'planner')['sources'].append(
            'AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html#no-such-section')
        self.assert_code('ANCHOR_MISSING', pol)

    def test_link_to_a_missing_file_fails(self):
        pol = fresh()
        role(pol, 'guest-root')['bootstrap']['evidence'] = ['evidence/F-99-nothing.md']
        self.assert_code('LINK_MISSING', pol)

    def test_link_outside_the_repository_fails(self):
        pol = fresh()
        role(pol, 'guest-root')['evidence'] = ['../outside.md']
        self.assert_code('LINK_INVALID', pol)

    def test_verify_at_must_be_a_plan_leaf(self):
        pol = fresh()
        role(pol, 'builder')['realization'][0]['verify_at'] = 'S-01.9'
        self.assert_code('DANGLING_REF', pol)

    def test_sunset_entry_needs_a_leaf_or_a_gap(self):
        pol = fresh()
        pol['non_roles'][0]['sunset'][2].pop('gap')
        self.assert_code('SCHEMA', pol)
        pol = fresh()
        pol['non_roles'][0]['sunset'][0]['at'] = 'S-01.9'
        self.assert_code('DANGLING_REF', pol)

    def test_non_role_reach_must_be_a_principal(self):
        pol = fresh()
        pol['non_roles'][0]['inherits_reach_of'] = 'someone'
        self.assert_code('DANGLING_REF', pol)

    def test_readme_must_name_every_role(self):
        readme = README.replace('`guest-login-agent`', 'guest-login-agent')
        found, problems = codes(fresh(), None, readme)
        self.assertIn('README_MISSING', found)
        self.assertTrue(any(p.where == 'guest-login-agent' for p in problems))

    def test_readme_tables_must_match_the_render(self):
        readme = README.replace('| `guest-root` Guest root |', '| `guest-root` Guest root, edited |')
        self.assertNotEqual(readme, README)
        self.assert_code('README_STALE', fresh(), readme)
        block = crt.generated_block(README)
        self.assert_code('README_STALE', fresh(), README.replace(crt.GENERATED_END, ''))
        self.assertTrue(block)


if __name__ == '__main__':
    unittest.main()
