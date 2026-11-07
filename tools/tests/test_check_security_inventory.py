"""Tests for tools/check_security_inventory.py and security/inventory.json (plan leaf S-01.1).

Run from the repository root:  python -I -B -m unittest discover -s tools/tests -v

The committed inventory must pass. Each negative case mutates an in-memory copy of it
(or a copy in a temporary directory, for the command line) and must fail with the
expected code. The checkout is only read.
"""
from pathlib import Path
import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]
CHECKER = REPO / 'tools' / 'check_security_inventory.py'
INVENTORY_PATH = REPO / 'security' / 'inventory.json'
README_PATH = REPO / 'security' / 'README.md'

_spec = importlib.util.spec_from_file_location('check_security_inventory', CHECKER)
csi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(csi)

INVENTORY = json.loads(INVENTORY_PATH.read_text(encoding='utf-8'))
README = README_PATH.read_text(encoding='utf-8')


def fresh():
    return copy.deepcopy(INVENTORY)


def entry(inv, collection, ident):
    for item in inv[collection]:
        if item['id'] == ident:
            return item
    raise AssertionError(f'fixture has no {collection} entry {ident!r}')


def codes(inv, readme=README):
    problems = csi.check(inv, REPO, readme)
    return {p.code for p in problems}, problems


def run_cli(*args):
    return subprocess.run([sys.executable, '-I', '-B', str(CHECKER), *map(str, args)],
                          capture_output=True, text=True, encoding='utf-8', cwd=REPO)


class CommittedInventory(unittest.TestCase):
    def test_inventory_passes(self):
        found, problems = codes(fresh())
        self.assertEqual(problems, [], '\n'.join(map(str, problems)))

    def test_every_privileged_operation_has_one_existing_principal(self):
        principals = {p['id'] for p in INVENTORY['principals']}
        self.assertTrue(INVENTORY['operations'])
        for op in INVENTORY['operations']:
            self.assertIsInstance(op['principal'], str, op['id'])
            self.assertIn(op['principal'], principals, op['id'])

    def test_no_agent_principal_holds_privileged_authority(self):
        agents = {p['id'] for p in INVENTORY['principals'] if p['agent_controlled']}
        self.assertIn('engineering-agent', agents)
        self.assertIn('bootstrap-host-agents', agents)
        for cred in INVENTORY['credentials']:
            custody = {cred['holder'], cred['manager'], *cred['readable_by']}
            if cred['authority'] in csi.PRIVILEGED_AUTHORITIES:
                self.assertFalse(custody & agents, cred['id'])
        for p in INVENTORY['principals']:
            if p['agent_controlled']:
                self.assertFalse(p['owner_authority'], p['id'])

    def test_bootstrap_agents_are_not_isolated_principals(self):
        bootstrap = entry(INVENTORY, 'principals', 'bootstrap-host-agents')
        self.assertFalse(bootstrap['independently_isolated'])
        self.assertEqual(bootstrap['shares_os_identity_with'], 'owner-os-account')

    def test_statuses_are_the_closed_set(self):
        self.assertEqual(sorted(INVENTORY['statuses']), sorted(csi.STATUSES))

    def test_cli_passes_and_lists(self):
        result = run_cli('--list')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS security/inventory.json', result.stdout)
        self.assertIn('op-as-conversation-create: management-dispatcher (planned)', result.stdout)
        self.assertIn('[Owner-only]', result.stdout)

    def test_cli_fails_on_a_mutated_copy(self):
        inv = fresh()
        del entry(inv, 'operations', 'op-as-conversation-create')['principal']
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'inventory.json'
            path.write_text(json.dumps(inv), encoding='utf-8')
            result = run_cli('--inventory', path, '--readme', README_PATH)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('PRINCIPAL_NOT_ONE', result.stdout)

    def test_cli_cannot_run_without_an_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_cli('--inventory', Path(tmp) / 'absent.json')
        self.assertEqual(result.returncode, 2)


class NamedPrincipal(unittest.TestCase):
    def test_unnamed_principal_fails(self):
        inv = fresh()
        del entry(inv, 'operations', 'op-as-conversation-create')['principal']
        found, _ = codes(inv)
        self.assertIn('PRINCIPAL_NOT_ONE', found)

    def test_two_principals_fail(self):
        inv = fresh()
        entry(inv, 'operations', 'op-guest-lifecycle')['principal'] = [
            'owner-os-account', 'management-dispatcher']
        found, _ = codes(inv)
        self.assertIn('PRINCIPAL_NOT_ONE', found)

    def test_a_principals_list_fails_even_beside_a_principal(self):
        inv = fresh()
        entry(inv, 'operations', 'op-guest-lifecycle')['principals'] = ['owner-os-account']
        found, _ = codes(inv)
        self.assertIn('PRINCIPAL_NOT_ONE', found)

    def test_nonexistent_principal_fails(self):
        inv = fresh()
        entry(inv, 'operations', 'op-effect-apply')['principal'] = 'somebody'
        found, _ = codes(inv)
        self.assertIn('DANGLING_REF', found)


class AgentAndOwnerAuthority(unittest.TestCase):
    def test_agent_held_token_with_owner_authority_fails(self):
        inv = fresh()
        entry(inv, 'credentials', 'cred-gitea-bot-builder')['authority'] = 'owner'
        found, problems = codes(inv)
        self.assertIn('AGENT_PRIVILEGED_CREDENTIAL', found)
        self.assertIn('AGENT_OWNER_AUTHORITY', found)
        self.assertTrue(any('cred-gitea-bot-builder' in p.where for p in problems))

    def test_agent_managed_admin_credential_fails(self):
        inv = fresh()
        entry(inv, 'credentials', 'cred-gitea-admin')['manager'] = 'reviewer-agent'
        found, _ = codes(inv)
        self.assertIn('AGENT_PRIVILEGED_CREDENTIAL', found)

    def test_agent_readable_management_key_fails(self):
        inv = fresh()
        entry(inv, 'credentials', 'cred-agent-server-session-key')['readable_by'].append(
            'engineering-agent')
        found, _ = codes(inv)
        self.assertIn('AGENT_PRIVILEGED_CREDENTIAL', found)

    def test_owner_only_operation_with_agent_readable_credential_fails(self):
        inv = fresh()
        cred = entry(inv, 'credentials', 'cred-owner-github')
        cred['authority'] = 'provider'  # even outside the privileged classes
        cred['readable_by'].append('ci-job')
        found, problems = codes(inv)
        self.assertIn('AGENT_OWNER_ONLY', found)
        self.assertTrue(any('op-git-push-public' in p.where for p in problems))

    def test_agent_described_with_owner_authority_fails(self):
        inv = fresh()
        entry(inv, 'principals', 'engineering-agent')['owner_authority'] = True
        found, _ = codes(inv)
        self.assertIn('AGENT_OWNER_AUTHORITY', found)

    def test_service_described_with_owner_authority_fails(self):
        inv = fresh()
        entry(inv, 'principals', 'management-dispatcher')['owner_authority'] = True
        found, _ = codes(inv)
        self.assertIn('AGENT_OWNER_AUTHORITY', found)

    def test_owner_credential_held_without_owner_authority_fails(self):
        inv = fresh()
        entry(inv, 'credentials', 'cred-gitea-owner-account')['holder'] = 'gitea-site-admin'
        found, _ = codes(inv)
        self.assertIn('AGENT_OWNER_AUTHORITY', found)

    def test_agent_kind_cannot_be_relabelled_trusted(self):
        inv = fresh()
        entry(inv, 'principals', 'ci-job')['agent_controlled'] = False
        found, _ = codes(inv)
        self.assertIn('AGENT_KIND', found)

    def test_owner_only_operation_needs_an_owner_principal(self):
        inv = fresh()
        entry(inv, 'operations', 'op-protected-merge')['principal'] = 'authorization-verifier'
        found, _ = codes(inv)
        self.assertIn('OWNER_ONLY_PRINCIPAL', found)

    def test_owner_only_operation_assigned_to_an_agent_fails(self):
        inv = fresh()
        entry(inv, 'operations', 'op-policy-change')['principal'] = 'bootstrap-host-agents'
        found, _ = codes(inv)
        self.assertIn('AGENT_OWNER_ONLY', found)
        self.assertIn('OWNER_ONLY_PRINCIPAL', found)

    def test_agent_operation_using_a_privileged_credential_fails(self):
        inv = fresh()
        entry(inv, 'operations', 'op-open-proposal-pr')['credentials'].append(
            'cred-agent-server-session-key')
        found, _ = codes(inv)
        self.assertIn('AGENT_PRIVILEGED_CREDENTIAL', found)

    def test_conversation_creation_by_an_agent_fails(self):
        inv = fresh()
        entry(inv, 'operations', 'op-as-conversation-create')['principal'] = 'engineering-agent'
        found, _ = codes(inv)
        self.assertIn('AGENT_PRIVILEGED_CREDENTIAL', found)


class SharedOsIdentity(unittest.TestCase):
    def test_owner_account_agents_cannot_be_called_isolated(self):
        inv = fresh()
        entry(inv, 'principals', 'bootstrap-host-agents')['independently_isolated'] = True
        found, _ = codes(inv)
        self.assertIn('SHARED_IDENTITY_ISOLATED', found)

    def test_shared_identity_needs_a_finding(self):
        inv = fresh()
        entry(inv, 'principals', 'bootstrap-host-agents')['findings'] = []
        found, _ = codes(inv)
        self.assertIn('SHARED_IDENTITY_UNDISCLOSED', found)

    def test_reachable_privileged_credential_must_name_the_agent(self):
        inv = fresh()
        finding = entry(inv, 'findings', 'fd-bootstrap-shared-identity')
        finding['refs'] = [r for r in finding['refs'] if r != 'bootstrap-host-agents']
        found, problems = codes(inv)
        self.assertIn('SHARED_IDENTITY_UNDISCLOSED', found)
        self.assertTrue(any('cred-guest-ssh-key' in p.where for p in problems))


class References(unittest.TestCase):
    def test_dangling_asset_custodian_fails(self):
        inv = fresh()
        entry(inv, 'assets', 'guest-moby-socket')['custodian'] = 'docker-daemon'
        found, _ = codes(inv)
        self.assertIn('DANGLING_REF', found)

    def test_dangling_credential_holder_fails(self):
        inv = fresh()
        entry(inv, 'credentials', 'cred-oh-secret-key')['holder'] = 'nobody'
        found, _ = codes(inv)
        self.assertIn('DANGLING_REF', found)

    def test_dangling_operation_credential_fails(self):
        inv = fresh()
        entry(inv, 'operations', 'op-guest-exec')['credentials'].append('cred-missing')
        found, _ = codes(inv)
        self.assertIn('DANGLING_REF', found)

    def test_dangling_finding_reference_fails(self):
        inv = fresh()
        entry(inv, 'assets', 'listener-host-qmp')['findings'] = ['fd-not-recorded']
        found, _ = codes(inv)
        self.assertIn('DANGLING_REF', found)

    def test_finding_naming_a_missing_entry_fails(self):
        inv = fresh()
        entry(inv, 'findings', 'fd-host-loopback-exposure')['refs'].append('listener-ghost')
        found, _ = codes(inv)
        self.assertIn('DANGLING_REF', found)

    def test_missing_trust_domain_fails(self):
        inv = fresh()
        entry(inv, 'principals', 'guest-root')['domain'] = 'td-nowhere'
        found, _ = codes(inv)
        self.assertIn('DANGLING_REF', found)

    def test_missing_domain_only_allowed_when_unknown(self):
        inv = fresh()
        entry(inv, 'principals', 'reviewer-agent')['domain'] = None
        found, _ = codes(inv)
        self.assertIn('DANGLING_REF', found)

    def test_unknown_plan_leaf_fails(self):
        inv = fresh()
        entry(inv, 'findings', 'fd-release-job-principal')['carried_to'].append('S-01.9')
        found, _ = codes(inv)
        self.assertIn('DANGLING_REF', found)

    def test_duplicate_id_fails(self):
        inv = fresh()
        entry(inv, 'assets', 'api-moby')['id'] = 'guest-root'
        found, _ = codes(inv)
        self.assertIn('ID_DUPLICATE', found)


class StatusesAndLinks(unittest.TestCase):
    def test_status_outside_the_closed_set_fails(self):
        inv = fresh()
        entry(inv, 'assets', 'api-moby')['status'] = 'verified'
        found, _ = codes(inv)
        self.assertIn('STATUS_INVALID', found)

    def test_observed_without_evidence_fails(self):
        inv = fresh()
        entry(inv, 'assets', 'guest-moby-socket')['evidence'] = []
        found, _ = codes(inv)
        self.assertIn('STATUS_UNSUPPORTED', found)

    def test_planned_without_sources_fails(self):
        inv = fresh()
        entry(inv, 'operations', 'op-effect-apply')['sources'] = []
        found, _ = codes(inv)
        self.assertIn('STATUS_UNSUPPORTED', found)

    def test_unknown_without_finding_fails(self):
        inv = fresh()
        entry(inv, 'operations', 'op-release-signing-deploy')['findings'] = []
        found, _ = codes(inv)
        self.assertIn('STATUS_UNSUPPORTED', found)

    def test_conflict_needs_a_conflict_finding(self):
        inv = fresh()
        entry(inv, 'operations', 'op-release-signing-deploy')['status'] = 'conflict'
        found, _ = codes(inv)
        self.assertIn('STATUS_UNSUPPORTED', found)

    def test_observed_principal_needs_an_observed_identity(self):
        inv = fresh()
        entry(inv, 'principals', 'guest-root')['identity']['observed'] = None
        found, _ = codes(inv)
        self.assertIn('STATUS_UNSUPPORTED', found)

    def test_undecided_rotation_owner_needs_a_finding(self):
        inv = fresh()
        cred = entry(inv, 'credentials', 'cred-verifier-read')
        cred['rotation_revocation_owner'] = None
        cred['findings'] = []
        found, _ = codes(inv)
        self.assertIn('STATUS_UNSUPPORTED', found)

    def test_evidence_link_to_a_missing_file_fails(self):
        inv = fresh()
        entry(inv, 'assets', 'api-moby')['evidence'] = ['evidence/F-99-nothing.md']
        found, _ = codes(inv)
        self.assertIn('LINK_MISSING', found)

    def test_blueprint_anchor_must_exist(self):
        inv = fresh()
        entry(inv, 'operations', 'op-protected-merge')['sources'] = [
            'AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html#no-such-section']
        found, _ = codes(inv)
        self.assertIn('ANCHOR_MISSING', found)

    def test_plan_anchor_must_be_a_work_package(self):
        inv = fresh()
        entry(inv, 'operations', 'op-as-runtime-stop')['sources'] = [
            'AI_Engineering_Implementation_Project_Plan_Overseer_Prompts_2026-10-31.json#S-01.9']
        found, _ = codes(inv)
        self.assertIn('ANCHOR_MISSING', found)

    def test_link_outside_the_repository_fails(self):
        inv = fresh()
        entry(inv, 'assets', 'api-moby')['evidence'] = ['../outside.md']
        found, _ = codes(inv)
        self.assertIn('LINK_INVALID', found)


class Publication(unittest.TestCase):
    def test_machine_path_fails(self):
        for text in ('C:\\Users\\you\\state', 'D:/guest-state/instances',
                     '\\\\server\\share', '%USERPROFILE%\\.ssh'):
            with self.subTest(text=text):
                inv = fresh()
                entry(inv, 'assets', 'host-guest-state-root')['location'] = text
                found, _ = codes(inv)
                self.assertIn('MACHINE_PATH', found)

    def test_urls_and_guest_paths_are_not_machine_paths(self):
        for text in ('unix:///var/run/docker.sock', 'https://example.org/x', '/srv/scratch/openhands'):
            with self.subTest(text=text):
                self.assertIsNone(csi.MACHINE_PATH.search(text))

    def test_readme_must_name_every_operation_and_finding(self):
        found, problems = codes(fresh(), README.replace('`op-exchange`', 'op-exchange'))
        self.assertIn('README_MISSING', found)
        self.assertTrue(any('op-exchange' in p.where for p in problems))


if __name__ == '__main__':
    unittest.main()
