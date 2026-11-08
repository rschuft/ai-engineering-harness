"""Tests for tools/check_containment_cases.py and security/containment-cases.json (S-02.1).

Run from the repository root:  python -I -B -m unittest discover -s tools/tests -v

The committed catalogue must pass against the committed inventory, properties, network
matrix, profile and README. Each negative case mutates an in-memory copy of the catalogue
(or a copy in a temporary directory for the command line) and must fail with the expected
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
CHECKER = REPO / 'tools' / 'check_containment_cases.py'
CATALOGUE_PATH = REPO / 'security' / 'containment-cases.json'
README_PATH = REPO / 'security' / 'README.md'
INVENTORY_PATH = REPO / 'security' / 'inventory.json'

_spec = importlib.util.spec_from_file_location('check_containment_cases', CHECKER)
ccc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ccc)

CATALOGUE = json.loads(CATALOGUE_PATH.read_text(encoding='utf-8'))
INVENTORY = json.loads(INVENTORY_PATH.read_text(encoding='utf-8'))
README = README_PATH.read_text(encoding='utf-8')


def fresh():
    return copy.deepcopy(CATALOGUE)


def case(c, ident):
    return next(x for x in c['cases'] if x['id'] == ident)


def codes(c, readme=README, inventory=None):
    return [p.code for p in ccc.check(c, inventory or INVENTORY, REPO, readme)]


class Committed(unittest.TestCase):
    category = 'contract'

    def test_catalogue_passes(self):
        problems = ccc.check(CATALOGUE, INVENTORY, REPO, README)
        self.assertEqual([str(p) for p in problems], [])

    def test_every_category_has_denials_controls_and_a_mutation(self):
        for cat in ccc.CATEGORIES:
            kinds = {x['kind'] for x in CATALOGUE['cases'] if x['category'] == cat}
            self.assertIn('denial', kinds, cat)
        mutated = {case(CATALOGUE, m['case'])['category'] for m in CATALOGUE['mutations']}
        self.assertEqual(mutated, set(ccc.CATEGORIES))

    def test_every_probe_has_enforcement_and_a_permitted_control(self):
        """The leaf's acceptance, read from the committed data."""
        by_id = {x['id']: x for x in CATALOGUE['cases']}
        for x in CATALOGUE['cases']:
            if x['kind'] == 'permitted':
                self.assertIsNone(x['positive_control'], x['id'])
                continue
            self.assertTrue(x['enforcement'], x['id'])
            self.assertTrue(all(e['refs'] for e in x['enforcement']), x['id'])
            self.assertEqual(by_id[x['positive_control']]['kind'], 'permitted', x['id'])

    def test_render_is_the_readme_block(self):
        block = ccc.generated_block(README)
        self.assertIsNotNone(block)
        self.assertEqual(block.strip(), ccc.render(CATALOGUE).strip())
        for x in CATALOGUE['cases']:
            self.assertIn(f"`{x['id']}`", block)

    def test_carried_findings_are_named(self):
        carried = {f for x in CATALOGUE['cases'] for f in x.get('carried') or []}
        for want in ('fd-container-shares-service-uid', 'fd-job-image-engine-clients',
                     'fd-container-network-deviations'):
            self.assertIn(want, carried)

    def test_network_none_recorded_as_a_deviation(self):
        x = case(CATALOGUE, 'egr-network-none')
        self.assertEqual(x['kind'], 'deviation')
        self.assertEqual(x['expected']['outcomes'], ['bridge'])
        self.assertTrue(x['compensated_by'])


class Rules(unittest.TestCase):
    def test_category_without_denial(self):
        c = fresh()
        c['cases'] = [x for x in c['cases'] if not (x['category'] == 'socket' and x['kind'] == 'denial')]
        c['mutations'] = [m for m in c['mutations'] if m['case'] in {x['id'] for x in c['cases']}]
        self.assertIn('CATEGORY_MISSING', codes(c, readme=None))

    def test_enforcement_missing(self):
        c = fresh()
        case(c, 'file-shadow')['enforcement'] = []
        self.assertIn('ENFORCEMENT_MISSING', codes(c, readme=None))

    def test_enforcement_location_unknown(self):
        c = fresh()
        case(c, 'file-shadow')['enforcement'][0]['location'] = 'hope'
        self.assertIn('ENFORCEMENT_MISSING', codes(c, readme=None))

    def test_enforcement_without_refs(self):
        c = fresh()
        case(c, 'file-shadow')['enforcement'][0]['refs'] = []
        self.assertIn('SCHEMA', codes(c, readme=None))

    def test_dangling_references(self):
        for ref in ('P99', 'nm-nowhere', 'asset-nowhere'):
            c = fresh()
            case(c, 'file-shadow')['enforcement'][0]['refs'] = [ref]
            self.assertIn('DANGLING_REF', codes(c, readme=None), ref)

    def test_references_of_each_kind_resolve(self):
        c = fresh()
        case(c, 'file-shadow')['enforcement'][0]['refs'] = [
            'P8', 'nm-job-engine', 'conversation-container', 'fd-container-shares-service-uid',
            'cred-conversation-keys']
        self.assertEqual(codes(c, readme=None), [])

    def test_principal_assets_and_findings_resolve(self):
        for field, value in (('principal', {'id': 'nobody', 'user': 'x', 'root_attempt': False}),
                             ('assets', ['no-asset']), ('carried', ['fd-none'])):
            c = fresh()
            case(c, 'file-shadow')[field] = value
            self.assertIn('DANGLING_REF', codes(c, readme=None), field)

    def test_assets_required(self):
        c = fresh()
        case(c, 'file-shadow')['assets'] = []
        self.assertIn('SCHEMA', codes(c, readme=None))

    def test_control_missing_or_not_permitted(self):
        c = fresh()
        case(c, 'file-shadow')['positive_control'] = None
        self.assertIn('CONTROL_MISSING', codes(c, readme=None))
        c = fresh()
        case(c, 'file-shadow')['positive_control'] = 'no-such-case'
        self.assertIn('CONTROL_MISSING', codes(c, readme=None))
        c = fresh()
        case(c, 'file-shadow')['positive_control'] = 'file-root-home'
        self.assertIn('CONTROL_INVALID', codes(c, readme=None))
        c = fresh()
        case(c, 'ctl-read-own-file')['positive_control'] = 'ctl-list-own-dir'
        self.assertIn('CONTROL_INVALID', codes(c, readme=None))

    def test_planned_control_for_an_executable_case(self):
        c = fresh()
        ctl = case(c, 'ctl-read-own-file')
        ctl['status'], ctl['verify_at'] = 'planned', 'S-02.2'
        self.assertIn('CONTROL_INVALID', codes(c, readme=None))

    def test_planned_case_needs_a_leaf(self):
        c = fresh()
        case(c, 'file-shadow')['status'] = 'planned'
        self.assertIn('STATUS_UNSUPPORTED', codes(c, readme=None))

    def test_expected_rules(self):
        c = fresh()
        case(c, 'file-shadow')['expected']['outcomes'] = ['EACCES', 'ok']
        self.assertIn('EXPECTED_INVALID', codes(c, readme=None))
        c = fresh()
        case(c, 'ctl-read-own-file')['expected']['outcomes'] = ['ENOENT']
        self.assertIn('EXPECTED_INVALID', codes(c, readme=None))
        c = fresh()
        case(c, 'file-shadow')['expected']['outcomes'] = []
        self.assertIn('EXPECTED_INVALID', codes(c, readme=None))
        c = fresh()
        case(c, 'priv-no-new-privs')['expected']['outcomes'] = ['ok']
        self.assertIn('EXPECTED_INVALID', codes(c, readme=None))

    def test_deviation_needs_compensating_cases(self):
        c = fresh()
        case(c, 'egr-network-none')['compensated_by'] = []
        self.assertIn('SCHEMA', codes(c, readme=None))
        c = fresh()
        case(c, 'egr-network-none')['compensated_by'] = ['ctl-read-own-file']
        self.assertIn('DEVIATION', codes(c, readme=None))
        c = fresh()
        case(c, 'file-shadow')['compensated_by'] = ['file-root-home']
        self.assertIn('SCHEMA', codes(c, readme=None))

    def test_probe_rules(self):
        c = fresh()
        case(c, 'file-shadow')['probe']['source'] = 'somewhere'
        self.assertIn('PROBE_INVALID', codes(c, readme=None))
        c = fresh()
        case(c, 'sock-run-docker')['probe']['extract'] = 'nothing'
        self.assertIn('PROBE_INVALID', codes(c, readme=None))
        c = fresh()
        del case(c, 'sock-run-docker')['probe']['args']['path']
        self.assertIn('PROBE_INVALID', codes(c, readme=None))
        c = fresh()
        del case(c, 'file-shadow')['probe']['args']['path']
        self.assertIn('PROBE_INVALID', codes(c, readme=None))
        c = fresh()
        case(c, 'file-shadow')['probe']['args']['path'] = 'etc/shadow'
        self.assertIn('PROBE_INVALID', codes(c, readme=None))
        for op, args in (('mountinfo', {'check': 'x'}), ('socket', {'type': 'packet'}),
                         ('unshare', {'flags': ['pid']}), ('mknod', {'kind': 'block'}),
                         ('init-module', {'variant': 'load'})):
            c = fresh()
            case(c, 'file-shadow')['probe'] = {'source': 'containment-probe', 'op': op, 'args': args}
            self.assertIn('PROBE_INVALID', codes(c, readme=None), op)

    def test_destructive_attempts(self):
        bad = [
            {'source': 'containment-probe', 'op': 'unlink', 'args': {'path': '/etc/shadow'}},
            {'source': 'containment-probe', 'op': 'exec', 'args': {'argv': ['rm', '-rf', '/x']}},
            {'source': 'containment-probe', 'op': 'exec', 'args': {'argv': ['/bin/kill', '1']}},
            {'source': 'containment-probe', 'op': 'exec', 'args': {'argv': ['mount', '-t', 'tmpfs']}},
            {'source': 'containment-probe', 'op': 'exec', 'args': {'argv': ['chmod', '777', '/']}},
            {'source': 'containment-probe', 'op': 'exec', 'args': {'argv': ['reboot']}},
            {'source': 'containment-probe', 'op': 'exec', 'args': {'argv': ['docker', 'rm', 'x']}},
            {'source': 'containment-probe', 'op': 'exec', 'args': {'argv': ['ctr', 'run', 'x']}},
            {'source': 'containment-probe', 'op': 'exec', 'args': {'argv': ['sudo', 'rm', 'x']}},
            {'source': 'containment-probe', 'op': 'exec', 'args': {'argv': ['python3', '-c', 'x']}},
            {'source': 'containment-probe', 'op': 'connect-tcp', 'args': {'host': '10.0.2.2', 'port': 22}},
            {'source': 'containment-probe', 'op': 'connect-tcp', 'args': {'host': '127.0.0.1', 'port': 'x'}},
            {'source': 'containment-probe', 'op': 'mknod', 'args': {'kind': 'char', 'path': '/dev/x'}},
            {'source': 'containment-probe', 'op': 'own-workspace', 'args': {'path': '/etc'}},
            {'source': 'job-access-probe', 'extract': 'tcp', 'args': {'what': 'to 8.8.4.4:53'}},
        ]
        for probe in bad:
            c = fresh()
            case(c, 'file-shadow')['probe'] = probe
            self.assertIn('DESTRUCTIVE', codes(c, readme=None), json.dumps(probe))

    def test_off_host_only_through_the_s014_sweeps(self):
        c = fresh()
        case(c, 'egr-offlink-no-route')['attempt'] += ' (1.1.1.1)'
        self.assertEqual(codes(c, readme=None), [])
        c = fresh()
        case(c, 'file-shadow')['attempt'] += ' via 1.1.1.1'
        self.assertIn('DESTRUCTIVE', codes(c, readme=None))

    def test_route_present_needs_the_falsification_guest(self):
        c = fresh()
        del case(c, 'egr-offlink-route-present')['requires']
        self.assertIn('DESTRUCTIVE', codes(c, readme=None))

    def test_profile_value_must_match(self):
        c = fresh()
        case(c, 'file-guest-session-key')['probe']['args']['path'] = '/var/lib/aieh/other.key'
        self.assertIn('PROFILE_VALUE', codes(c, readme=None))
        c = fresh()
        case(c, 'file-guest-session-key')['probe']['args']['profile_value'] = 'provisioning.none'
        self.assertIn('PROFILE_VALUE', codes(c, readme=None))

    def test_mutations(self):
        c = fresh()
        c['mutations'][0]['case'] = 'ctl-read-own-file'
        self.assertIn('MUTATION_INVALID', codes(c, readme=None))
        c = fresh()
        c['mutations'][0]['op'] = 'exec'
        c['mutations'][0]['args'] = {'argv': ['rm', 'x']}
        self.assertIn('DESTRUCTIVE', codes(c, readme=None))
        c = fresh()
        c['mutations'] = [m for m in c['mutations'] if m['id'] != 'mut-egress']
        self.assertIn('MUTATION_MISSING', codes(c, readme=None))
        c = fresh()
        c['mutations'][1]['id'] = c['mutations'][0]['id']
        self.assertIn('MUTATION_INVALID', codes(c, readme=None))
        c = fresh()
        c['mutations'][0]['note'] = ''
        self.assertIn('MUTATION_INVALID', codes(c, readme=None))

    def test_ids(self):
        c = fresh()
        case(c, 'file-shadow')['id'] = 'File Shadow'
        self.assertIn('ID_INVALID', codes(c, readme=None))
        c = fresh()
        c['cases'].append(copy.deepcopy(case(c, 'file-shadow')))
        self.assertIn('ID_DUPLICATE', codes(c, readme=None))

    def test_unknown_keys_and_vocabularies(self):
        c = fresh()
        case(c, 'file-shadow')['surprise'] = 1
        self.assertIn('SCHEMA', codes(c, readme=None))
        c = fresh()
        c['surprise'] = 1
        self.assertIn('SCHEMA', codes(c, readme=None))
        for field, value in (('category', 'kernel'), ('kind', 'maybe'), ('status', 'done'),
                             ('depends_on', ['weather']), ('requires', ['luck'])):
            c = fresh()
            case(c, 'file-shadow')[field] = value
            self.assertIn('SCHEMA', codes(c, readme=None), field)
        c = fresh()
        del c['enforcement_locations']['icc']
        self.assertIn('SCHEMA', codes(c, readme=None))
        c = fresh()
        c['version'] = ''
        self.assertIn('SCHEMA', codes(c, readme=None))

    def test_fingerprints(self):
        c = fresh()
        c['fingerprints']['gitea']['builder'] = 'the-token-itself'
        self.assertIn('SCHEMA', codes(c, readme=None))
        c = fresh()
        c['fingerprints']['gitea'] = {}
        self.assertIn('SCHEMA', codes(c, readme=None))

    def test_machine_path(self):
        c = fresh()
        case(c, 'file-shadow')['attempt'] = 'read C:\\Users\\user\\x'
        self.assertIn('MACHINE_PATH', codes(c, readme=None))
        self.assertIn('MACHINE_PATH', codes(fresh(), readme=README + '\nD:\\x\n'))

    def test_readme_stale(self):
        c = fresh()
        case(c, 'file-shadow')['attempt'] = 'read /etc/shadow (changed)'
        self.assertIn('README_STALE', codes(c))
        self.assertIn('README_STALE', codes(fresh(), readme='no markers'))

    def test_wrong_types_never_crash(self):
        """Type fuzzing: every value replaced by every wrong type gives named failures."""
        values = (None, 'x', 5, [], {}, [None], [5], {'a': 1}, True)
        paths = [('version',), ('cases',), ('mutations',), ('scratch',), ('fingerprints',),
                 ('categories',)]
        for key in ccc.CASE_KEYS:
            paths.append(('cases', 0, key))
            paths.append(('cases', 30, key))
        for key in ('source', 'op', 'extract', 'args'):
            paths.append(('cases', 30, 'probe', key))
            paths.append(('cases', 50, 'probe', key))
        for key in ('outcomes', 'rule'):
            paths.append(('cases', 30, 'expected', key))
        for key in ccc.MUTATION_KEYS:
            paths.append(('mutations', 0, key))
        for path in paths:
            for value in values:
                c = fresh()
                node = c
                for part in path[:-1]:
                    node = node[part]
                if isinstance(node, list) and path[-1] >= len(node):
                    continue
                node[path[-1]] = value
                try:
                    ccc.check(c, INVENTORY, REPO, README)
                except Exception as exc:          # noqa: BLE001 - the test reports any crash
                    self.fail(f'{path} = {value!r} raised {type(exc).__name__}: {exc}')
        for value in values:
            ccc.check(value, INVENTORY, REPO, README)


class CommandLine(unittest.TestCase):
    category = 'contract'

    def run_cli(self, *args):
        return subprocess.run([sys.executable, '-I', '-B', str(CHECKER), *args], cwd=REPO,
                              capture_output=True, text=True)

    def test_pass_list_and_render(self):
        r = self.run_cli('--list')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('PASS security/containment-cases.json', r.stdout)
        self.assertIn('file-shadow: file denial (control ctl-read-own-file)', r.stdout)
        r = self.run_cli('--render')
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), ccc.render(CATALOGUE).strip())

    def test_fail_and_unreadable(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = fresh()
            case(c, 'file-shadow')['positive_control'] = None
            path = Path(tmp) / 'c.json'
            path.write_text(json.dumps(c), encoding='utf-8')
            r = self.run_cli('--catalogue', str(path))
            self.assertEqual(r.returncode, 1)
            self.assertIn('CONTROL_MISSING', r.stdout)
            r = self.run_cli('--catalogue', str(Path(tmp) / 'missing.json'))
            self.assertEqual(r.returncode, 2)


if __name__ == '__main__':
    unittest.main()
