"""Tests for tools/check_network_matrix.py and policy/network-matrix.json (plan leaf S-01.4).

Run from the repository root:  python -I -B -m unittest discover -s tools/tests -v

The committed matrix must pass against the committed inventory, profiles and README. Each
negative case mutates an in-memory copy of the matrix (or of the inventory or a profile,
or a copy in a temporary directory for the command line) and must fail with the expected
code. The checkout is only read.
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
CHECKER = REPO / 'tools' / 'check_network_matrix.py'
MATRIX_PATH = REPO / 'policy' / 'network-matrix.json'
README_PATH = REPO / 'policy' / 'README.md'
INVENTORY_PATH = REPO / 'security' / 'inventory.json'

_spec = importlib.util.spec_from_file_location('check_network_matrix', CHECKER)
cnm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cnm)

MATRIX_TEXT = MATRIX_PATH.read_text(encoding='utf-8')
MATRIX = json.loads(MATRIX_TEXT)
INVENTORY = json.loads(INVENTORY_PATH.read_text(encoding='utf-8'))
README = README_PATH.read_text(encoding='utf-8')
PROFILES = cnm.load_profiles(REPO)
QEMU = 'strong-windows-qemu-whpx'


def fresh():
    # A new parse of the committed text: equal to MATRIX and sharing nothing with it, as a deep
    # copy is, at a quarter of the cost (the type-fuzzing tests take hundreds; plan leaf F-09).
    return json.loads(MATRIX_TEXT)


def edge(m, ident):
    for item in m['edges'] + m['external_edges']:
        if item['id'] == ident:
            return item
    raise AssertionError(f'fixture has no edge {ident!r}')


def codes(m, inv=None, readme=README, profiles=None):
    problems = cnm.check(m, INVENTORY if inv is None else inv, REPO, readme,
                         profiles=PROFILES if profiles is None else profiles)
    return {p.code for p in problems}, problems


def shared_state(inputs):
    """What an evaluation must leave as it found it in the shared inputs."""
    return json.dumps([inputs.properties, inputs.profiles], sort_keys=True)


def run_cli(*args):
    return subprocess.run([sys.executable, '-I', '-B', str(CHECKER), *map(str, args)],
                          capture_output=True, text=True, encoding='utf-8', cwd=REPO)


class CommittedMatrix(unittest.TestCase):
    category = 'contract'

    def test_matrix_passes(self):
        found, problems = codes(fresh())
        self.assertEqual(problems, [], '\n'.join(map(str, problems)))

    def test_every_ordered_domain_pair_has_a_row(self):
        domains = [d['id'] for d in INVENTORY['trust_domains']]
        pairs = {(r['from'], r['to']) for r in MATRIX['edges']}
        self.assertEqual(len(domains), 9)
        self.assertEqual({(a, b) for a in domains for b in domains} - pairs, set())

    def test_every_planned_edge_names_the_leaf_that_observes_it(self):
        """Read straight from the data: a planned edge without verify_at has no observer."""
        missing = [r['id'] for r in MATRIX['edges'] + MATRIX['external_edges']
                   if r['status'] == 'planned' and not r.get('verify_at')]
        self.assertEqual(missing, [])

    def test_no_untrusted_allow_reaches_a_management_or_credential_asset(self):
        """The leaf's acceptance, read straight from the data, independently of the checker."""
        trust = {d['id']: d['trust'] for d in INVENTORY['trust_domains']}
        privileged = {c['id'] for c in INVENTORY['credentials']
                      if c['authority'] in ('owner', 'admin', 'executor', 'management')}
        for r in MATRIX['edges']:
            if r['verdict'] == 'allow' and trust[r['from']] in ('untrusted', 'contained') and \
                    trust[r['to']] in ('trusted', 'trusted-computing-base'):
                self.assertEqual(r['endpoint'], 'inference', r['id'])
                self.assertFalse(set(r['credentials']) & privileged, r['id'])
        # an untrusted job reaches no management API, engine, Gitea or host service
        for ident in ('nm-job-management-api', 'nm-job-engine', 'nm-job-gitea', 'nm-job-host',
                      'nm-job-guest-listeners', 'nm-job-peer', 'nm-ext-job-egress',
                      'nm-review-management-api', 'nm-review-gitea'):
            self.assertEqual(edge(MATRIX, ident)['verdict'], 'deny', ident)

    def test_required_workflows_are_allowed(self):
        for ident in ('nm-owner-guest-ssh', 'nm-owner-guest-exchange', 'nm-owner-guest-qmp',
                      'nm-owner-gitea', 'nm-guest-openhands-moby', 'nm-guest-login-agent-server',
                      'nm-guest-proxy-conversation', 'nm-job-own-server'):
            r = edge(MATRIX, ident)
            self.assertEqual((r['verdict'], r['status']), ('allow', 'observed'), ident)
        for ident in ('nm-dispatcher-agent-server', 'nm-owner-ui-conversation', 'nm-job-inference'):
            self.assertEqual(edge(MATRIX, ident)['owner_act'], True, ident)

    def test_owner_ui_never_holds_the_management_key(self):
        ui = [r for r in MATRIX['edges'] + MATRIX['external_edges']
              if r['id'].startswith('nm-owner-ui')]
        self.assertTrue(ui)
        for r in ui:
            self.assertNotIn('cred-agent-server-session-key', r['credentials'], r['id'])

    def test_cli_passes_and_lists(self):
        result = run_cli('--list')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS policy/network-matrix.json', result.stdout)
        self.assertIn('nm-owner-guest-ssh: td-owner -> td-guest-control allow (observed)',
                      result.stdout)

    def test_cli_render_matches_the_readme(self):
        result = run_cli('--render')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(cnm.generated_block(README).strip(), result.stdout.strip())
        self.assertNotIn('**missing**', result.stdout)

    def test_cli_fails_on_a_mutated_copy(self):
        m = fresh()
        m['edges'] = [r for r in m['edges'] if (r['from'], r['to']) != ('td-review', 'td-owner')]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'network-matrix.json'
            path.write_text(json.dumps(m), encoding='utf-8')
            result = run_cli('--matrix', path)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('PAIR_MISSING', result.stdout)

    def test_cli_cannot_run_without_a_matrix(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_cli('--matrix', Path(tmp) / 'missing.json')
        self.assertEqual(result.returncode, 2)


class Acceptance(unittest.TestCase):
    """The rules of the checker, each by a mutation that must fail with its code. The inputs the
    matrix is checked against (properties, profiles, the repository files the checks read) are
    loaded once for the class (``load_inputs``) and every mutation, a deep copy, is evaluated
    against them (``evaluate``); each test checks that they are unchanged. The committed matrix
    goes through the file-reading path end to end in ``CommittedMatrix`` (``test_matrix_passes``
    through ``check``, ``test_cli_passes_and_lists`` through the command line)."""

    @classmethod
    def setUpClass(cls):
        cls.inputs = cnm.load_inputs(REPO, profiles=PROFILES)
        cls.loaded = shared_state(cls.inputs)

    def tearDown(self):
        self.assertEqual(shared_state(self.inputs), self.loaded, 'an evaluation changed the shared inputs')

    def codes(self, m, inv=None, readme=README, profiles=None):
        problems = cnm.evaluate(m, INVENTORY if inv is None else inv, self.inputs, readme,
                                profiles=profiles)
        return {p.code for p in problems}, problems

    def assert_code(self, code, m, inv=None, where=None, readme=README, profiles=None):
        found, problems = self.codes(m, inv, readme, profiles)
        self.assertIn(code, found, '\n'.join(map(str, problems)))
        if where:
            self.assertTrue(any(p.code == code and where in p.where for p in problems),
                            '\n'.join(map(str, problems)))

    def test_a_missing_pair_fails(self):
        m = fresh()
        m['edges'] = [r for r in m['edges'] if (r['from'], r['to']) != ('td-untrusted-ci', 'td-git-hosting')]
        self.assert_code('PAIR_MISSING', m, where='td-untrusted-ci -> td-git-hosting')

    def test_a_contained_domain_without_an_external_row_fails(self):
        m = fresh()
        m['external_edges'] = [r for r in m['external_edges'] if r['from'] != 'td-guest-control']
        self.assert_code('PAIR_MISSING', m, where='td-guest-control -> external')

    def test_an_unclassifiable_row_fails(self):
        for key, value in (('verdict', 'maybe'), ('status', 'hoped'), ('protocol', ''),
                           ('endpoint', 'somewhere'), ('enforcement', 'yes')):
            m = fresh()
            edge(m, 'nm-job-peer')[key] = value
            self.assert_code('UNCLASSIFIED', m, where='nm-job-peer')
        m = fresh()
        edge(m, 'nm-job-peer')['enforcement'][0]['kind'] = 'hope'
        self.assert_code('UNCLASSIFIED', m, where='nm-job-peer')
        m = fresh()
        edge(m, 'nm-job-peer')['enforcement'][0]['where'] = 'cloud'
        self.assert_code('UNCLASSIFIED', m, where='nm-job-peer')
        m = fresh()
        edge(m, 'nm-job-peer')['exempt'] = True
        self.assert_code('SCHEMA', m, where='nm-job-peer')

    def test_an_untrusted_allow_into_management_fails(self):
        # into a trusted domain: an asset endpoint, the management class, a credential asset
        for endpoint in ('api-integration-service', 'management', 'gitea-server'):
            m = fresh()
            r = edge(m, 'nm-job-management')
            r.update(verdict='allow', endpoint=endpoint)
            self.assert_code('TRUST_BOUNDARY', m, where='nm-job-management')
        m = fresh()
        edge(m, 'nm-job-inference')['credentials'] = ['cred-agent-server-session-key']
        self.assert_code('TRUST_BOUNDARY', m, where='nm-job-inference')
        m = fresh()
        r = edge(m, 'nm-runner-gitea')
        r.update(verdict='allow', endpoint='gitea-server')
        self.assert_code('TRUST_BOUNDARY', m, where='nm-runner-gitea')
        # a class endpoint into a trusted domain is fine
        found, _ = self.codes(fresh())
        self.assertNotIn('TRUST_BOUNDARY', found)

    def test_allow_without_prevention_fails(self):
        m = fresh()
        r = edge(m, 'nm-owner-gitea')
        r['enforcement'] = [e for e in r['enforcement'] if e['kind'] != 'prevention'] + [
            {'mechanism': 'logged', 'kind': 'detection', 'where': 'gitea'}]
        self.assert_code('ALLOW_UNENFORCED', m, where='nm-owner-gitea')

    def test_disclosed_without_a_finding_and_deny_without_enforcement_fail(self):
        m = fresh()
        edge(m, 'nm-owner-same-account')['findings'] = []
        self.assert_code('DISCLOSED_UNSUPPORTED', m, where='nm-owner-same-account')
        m = fresh()
        edge(m, 'nm-job-peer')['enforcement'] = []
        self.assert_code('DENY_UNENFORCED', m, where='nm-job-peer')

    def test_dangling_references_fail(self):
        for key, value in (('from', 'td-nowhere'), ('to', 'td-nowhere'),
                           ('credentials', ['cred-nothing']), ('findings', ['fd-nothing']),
                           ('builds_at', 'Z-99.9'), ('verify_at', 'S-01.9'),
                           ('profile_endpoints', [f'{QEMU}:management:{{vnc_port}}'])):
            m = fresh()
            edge(m, 'nm-owner-guest-ssh')[key] = value
            self.assert_code('DANGLING_REF', m, where='nm-owner-guest-ssh')
        m = fresh()
        m['asset_classes']['asset-that-is-not'] = 'host'
        self.assert_code('DANGLING_REF', m, where='asset_classes.asset-that-is-not')

    def test_asset_classes_are_complete_and_consistent(self):
        m = fresh()
        del m['asset_classes']['gitea-server']
        self.assert_code('ASSET_UNCLASSIFIED', m, where='gitea-server')
        for aid, cls in (('guest-secrets-env-file', 'store'), ('api-agent-server-management', 'service'),
                         ('gitea-server', 'service'), ('guest-moby-socket', 'workload')):
            m = fresh()
            m['asset_classes'][aid] = cls
            self.assert_code('ASSET_CLASS', m, where=aid)
        # a new inventory asset is a failure until it is classified
        inv = copy.deepcopy(INVENTORY)
        inv['assets'].append(dict(inv['assets'][0], id='host-new-listener'))
        self.assert_code('ASSET_UNCLASSIFIED', fresh(), inv=inv, where='host-new-listener')

    def test_status_rules(self):
        m = fresh()
        edge(m, 'nm-job-peer')['evidence'] = []
        self.assert_code('STATUS_UNSUPPORTED', m, where='nm-job-peer')
        m = fresh()
        edge(m, 'nm-job-peer')['inspection'] = []
        self.assert_code('STATUS_UNSUPPORTED', m, where='nm-job-peer')
        m = fresh()
        r = edge(m, 'nm-verifier-gitea')
        r.pop('builds_at', None)
        r.pop('verify_at', None)
        self.assert_code('STATUS_UNSUPPORTED', m, where='nm-verifier-gitea')
        m = fresh()
        # a planned edge names the leaf that will observe it: builds_at alone is not enough
        r = edge(m, 'nm-verifier-gitea')
        self.assertEqual(r['status'], 'planned')
        self.assertTrue(r.get('builds_at'))
        r.pop('verify_at')
        self.assert_code('STATUS_UNSUPPORTED', m, where='nm-verifier-gitea')
        m = fresh()
        edge(m, 'nm-dispatcher-bot-gitea')['sources'] = ['profiles/README.md']
        self.assert_code('STATUS_UNSUPPORTED', m, where='nm-dispatcher-bot-gitea')
        m = fresh()
        edge(m, 'nm-dispatcher-bot-gitea').pop('builds_at')
        self.assert_code('STATUS_UNSUPPORTED', m, where='nm-dispatcher-bot-gitea')
        m = fresh()
        edge(m, 'nm-job-peer')['evidence'] = ['evidence/no-such-record.md']
        self.assert_code('LINK_MISSING', m, where='nm-job-peer')

    def test_active_profile_endpoints_must_be_allowed(self):
        for ident in ('nm-owner-guest-ssh', 'nm-owner-guest-qmp', 'nm-owner-guest-exchange'):
            m = fresh()
            edge(m, ident)['verdict'] = 'deny'
            self.assert_code('PROFILE_ENDPOINT', m)
        # a new forward in launch.argv is a failure until an allow row names it
        profiles = copy.deepcopy(PROFILES)
        argv = profiles[QEMU]['launch']['argv']
        i = argv.index('-netdev') + 1
        argv[i] += ',hostfwd=tcp:127.0.0.1:{as_port}-:8000'
        self.assert_code('PROFILE_ENDPOINT', fresh(), profiles=profiles,
                         where=f'{QEMU}:argv:hostfwd=tcp:127.0.0.1:{{as_port}}-:8000')
        # an endpoint that leaves its deferred status needs an allow row too
        profiles = copy.deepcopy(PROFILES)
        for e in profiles[QEMU]['network']['endpoints']:
            if e['class'] == 'inference':
                e['status'] = 'enabled'
        self.assert_code('PROFILE_ENDPOINT', fresh(), profiles=profiles, where=f'{QEMU}:inference')
        # a profile whose provider validation did not pass is not active
        profiles = copy.deepcopy(PROFILES)
        profiles[QEMU]['status']['provider_validation'] = 'UNKNOWN'
        argv = profiles[QEMU]['launch']['argv']
        argv[argv.index('-netdev') + 1] += ',hostfwd=tcp:127.0.0.1:1-:2'
        found, _ = self.codes(fresh(), profiles=profiles)
        self.assertNotIn('PROFILE_ENDPOINT', found)

    def test_observed_owner_act_needs_a_verbatim_approval(self):
        m = fresh()
        del edge(m, 'nm-owner-guest-ssh')['owner_approval']
        self.assert_code('OWNER_APPROVAL', m, where='nm-owner-guest-ssh')
        m = fresh()
        edge(m, 'nm-owner-gitea')['owner_approval']['quote'] = 'The Owner approved everything at once'
        self.assert_code('OWNER_APPROVAL', m, where='nm-owner-gitea')
        m = fresh()
        edge(m, 'nm-owner-gitea')['owner_approval']['link'] = 'decisions/0003-execution-guest-providers-and-isolation-contract.md'
        self.assert_code('OWNER_APPROVAL', m, where='nm-owner-gitea')
        m = fresh()
        r = edge(m, 'nm-job-inference')
        r.update(status='observed', evidence=['evidence/S-01.3.2-job-daemon-and-management-access.md'],
                 inspection=['x'])
        self.assert_code('OWNER_APPROVAL', m, where='nm-job-inference')
        m = fresh()
        edge(m, 'nm-job-peer')['owner_approval'] = {'link': 'evidence/bootstrap-log.md', 'quote': 'x' * 20}
        self.assert_code('SCHEMA', m, where='nm-job-peer')

    def test_ids_and_externals(self):
        m = fresh()
        m['edges'].append(copy.deepcopy(edge(m, 'nm-job-peer')))
        self.assert_code('ID_DUPLICATE', m)
        m = fresh()
        edge(m, 'nm-job-peer')['id'] = 'Job Peer'
        self.assert_code('ID_INVALID', m)
        m = fresh()
        edge(m, 'nm-ext-job-egress')['to'] = 'external:moon'
        self.assert_code('DANGLING_REF', m, where='nm-ext-job-egress')
        m = fresh()
        edge(m, 'nm-ext-job-egress')['to'] = 'td-owner'
        self.assert_code('SCHEMA', m, where='nm-ext-job-egress')
        m = fresh()
        edge(m, 'nm-job-peer')['to'] = 'external:off-host'          # not in a domain edge
        self.assert_code('DANGLING_REF', m, where='nm-job-peer')

    def test_machine_paths_and_readme(self):
        m = fresh()
        edge(m, 'nm-job-peer')['notes'] = 'see D:\\aieh-guest-state\\instances'
        self.assert_code('MACHINE_PATH', m)
        self.assert_code('README_MISSING', fresh(), readme=README.replace('`nm-job-peer`', 'nm-job-peer'),
                         where='nm-job-peer')
        self.assert_code('README_STALE', fresh(), readme=README.replace(cnm.GENERATED_BEGIN, ''))
        m = fresh()
        edge(m, 'nm-job-peer')['name'] = 'A renamed edge'
        self.assert_code('README_STALE', m)
        self.assert_code('MACHINE_PATH', fresh(), readme=README + '\nC:\\Users\\someone\n')

    def test_schema_and_types_never_crash(self):
        """Wrongly typed values give a named FAIL, never an exception."""
        values = (None, 'x', 5, [], {}, [None], [5], {'a': 1}, True)
        paths = [('edges',), ('external_edges',), ('asset_classes',), ('externals',),
                 ('verdicts',)]
        keys = ['id', 'from', 'to', 'verdict', 'protocol', 'endpoint', 'credentials',
                'enforcement', 'status', 'evidence', 'sources', 'builds_at', 'verify_at',
                'owner_act', 'owner_approval', 'findings', 'inspection', 'profile_endpoints']
        for v in values:
            for path in paths:
                m = fresh()
                m[path[0]] = v
                self.codes(m)
            for key in keys:
                m = fresh()
                edge(m, 'nm-owner-guest-ssh')[key] = v
                self.codes(m)
                m = fresh()
                edge(m, 'nm-owner-guest-ssh')['enforcement'] = [v]
                self.codes(m)
        self.assert_code('SCHEMA', 'not a matrix')


if __name__ == '__main__':
    unittest.main()
