"""Tests for tools/check_profile.py's fixture-profile branch (plan leaf E-01.8; the I1 integration design, R8 point 2
and R9; profiles/README.md section 13), offline: the checked-in fixture-d1-replay passes, and each rule fails a mutated
copy, loaded in memory and checked against a copy of profiles/.

Run from the repository root:

    python -I -B -m unittest discover -s tools/tests -p test_check_fixture_profile.py -v
"""
import copy
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
FIX = 'fixture-d1-replay'
LIVE = 'strong-windows-qemu-whpx'


def _load():
    module = sys.modules.get('check_profile')
    if module is None:
        spec = importlib.util.spec_from_file_location('check_profile', REPO / 'tools' / 'check_profile.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules['check_profile'] = module
        spec.loader.exec_module(module)
    return module


check_profile = _load()


class FixtureProfile(unittest.TestCase):
    category = 'contract'

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='fixprof-'))
        shutil.copytree(REPO / 'profiles', cls.tmp / 'profiles')
        cls.profile = json.loads((REPO / 'profiles' / FIX / 'profile.json').read_text(encoding='utf-8'))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def errors(self, profile, root=None):
        return check_profile.check(profile, root or self.tmp).errors

    def mutated(self, change):
        profile = copy.deepcopy(self.profile)
        change(profile)
        return self.errors(profile)

    def assertFails(self, change, needle):
        errors = self.mutated(change)
        self.assertTrue(any(needle in e for e in errors), (needle, errors))

    def test_the_checked_in_fixture_profile_passes(self):
        self.assertEqual(self.errors(self.profile, REPO), [])

    def test_a_launchable_section_is_refused(self):
        for key in ('launch', 'boot_inputs', 'state_dir', 'lifecycle', 'labels'):
            with self.subTest(key=key):
                self.assertFails(lambda p: p.__setitem__(key, {}), 'a fixture profile holds only')
        self.assertFails(lambda p: p['provider'].__setitem__('name', 'qemu'), 'provider: only the image pin')

    def test_the_name_and_the_declaration_go_together(self):
        self.assertFails(lambda p: p.__setitem__('name', 'strong-replay'), 'name: a profile that declares')
        self.assertFails(lambda p: p['provisioning']['agent_server'].__setitem__(
            'transport', {'authority': 'fixture', 'kind': 'other'}), 'declares exactly')
        self.assertFails(lambda p: p['provisioning']['agent_server'].pop('transport'), 'declares exactly')

    def test_every_admission_value_is_the_replayed_profiles(self):
        server = lambda p: p['provisioning']['agent_server']  # noqa: E731
        for label, change in (
                ('config.content', lambda p: server(p)['config']['content'].__setitem__('max_concurrent_runs', 4)),
                ('conversations', lambda p: server(p)['conversations'].__setitem__('source_root', '/srv/other')),
                ('ceilings', lambda p: p['ceilings'].__setitem__('vcpu', 4)),
                ('network.endpoints', lambda p: p['network']['endpoints'][0].__setitem__('guest_port', 1)),
                ('provider.provision_lock', lambda p: p['provider']['provision_lock'].__setitem__('sha256', '0' * 64)),
                ('version', lambda p: server(p).__setitem__('version', '1.60.2'))):
            with self.subTest(label=label):
                self.assertFails(change, label)

    def test_replays_must_name_the_profile_by_its_digest(self):
        self.assertFails(lambda p: p['replays'].__setitem__('sha256', '0' * 64), 'replays:')

    def test_operational_needs_its_evidence(self):
        self.assertFails(lambda p: p['status'].pop('operational_evidence'), 'conformance evidence')

    def test_the_allowlist_must_be_the_replayed_one_with_the_declaration(self):
        root = Path(tempfile.mkdtemp(prefix='fixprof-routes-'))
        self.addCleanup(shutil.rmtree, root, True)
        shutil.copytree(REPO / 'profiles', root / 'profiles')
        path = root / 'profiles' / FIX / 'agent-server' / 'routes.json'
        routes = json.loads(path.read_text(encoding='utf-8'))
        routes['routes'] = routes['routes'][1:]
        raw = (json.dumps(routes, indent=2) + '\n').encode('utf-8')
        path.write_bytes(raw)
        profile = copy.deepcopy(self.profile)
        profile['provisioning']['agent_server']['admission']['routes']['sha256'] = check_profile.sha256_file(path)
        self.assertTrue(any('the replayed allowlist with the transport added' in e
                            for e in self.errors(profile, root)))

    def test_a_live_profiles_allowlist_declaring_a_transport_is_refused(self):
        root = Path(tempfile.mkdtemp(prefix='fixprof-live-'))
        self.addCleanup(shutil.rmtree, root, True)
        shutil.copytree(REPO / 'profiles', root / 'profiles')
        path = root / 'profiles' / LIVE / 'agent-server' / 'routes.json'
        routes = json.loads(path.read_text(encoding='utf-8'))
        routes['transport'] = {'authority': 'fixture', 'kind': 'loopback-fixture'}
        path.write_bytes((json.dumps(routes, indent=2) + '\n').encode('utf-8'))
        live = json.loads((REPO / 'profiles' / LIVE / 'profile.json').read_text(encoding='utf-8'))
        live['provisioning']['agent_server']['admission']['routes']['sha256'] = check_profile.sha256_file(path)
        errors = check_profile.check(live, root).errors
        self.assertTrue(any('declares a transport the profile does not' in e for e in errors), errors)


if __name__ == '__main__':
    unittest.main()
