"""Tests for the D1 manifest candidate (plan leaf E-05.3), offline.

Run from the repository root, under the tools interpreter (Dulwich is required):

    <tools python> -I -B -m unittest discover -s integrations/dispatch/tests -p test_d1_candidate.py -v

``integrations/dispatch/candidates/d1-approved-inputs.json`` is the manifest planning promotes for D1 (the
commitment ``commitment-d1-2026-11-15``, "The D1 manifest"). These tests hold it to the checked-in files: its
entries are exactly the commitment's five; its profile digest is the checked-in ``profile.json``'s (a profile
change without a new candidate and a new promotion fails here); its pin's digest is the checked-in assignment's;
and, in a clone with its history, the assignment at the pinned commit passes the resolver's own check.
"""
from pathlib import Path
import hashlib
import importlib.util
import json
import sys
import unittest

CATEGORY = 'integration'

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]


def _load(name, path):
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


di = _load('dispatch_inputs', REPO / 'integrations' / 'dispatch' / 'dispatch_inputs.py')

CANDIDATE = REPO / 'integrations' / 'dispatch' / 'candidates' / 'd1-approved-inputs.json'
PROFILE = 'strong-windows-qemu-whpx'
PIN = 'd1-implement'
DEMO, CHANGE = 'aieh-d1-demo', 'add-slugify'
# C2 of aieh-demo/aieh-d1-demo: the acceptance recorder's commit, which accept-design binds (E-05.1, section 9).
C2 = 'dd18102dccfcfeac5ea0cd11c40e3e052d11a4b3'


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TheD1Candidate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = CANDIDATE.read_bytes()
        cls.manifest = di.parse_manifest(cls.raw)
        cls.data = json.loads(cls.raw)
        cls.pin = cls.data['catalog_pins'][0]

    def test_its_entries_are_the_commitments(self):
        self.assertEqual(self.data['repositories'], [{'id': DEMO}])
        self.assertEqual(self.data['designs'], [{'repository': DEMO, 'change': CHANGE, 'commit': C2}])
        self.assertEqual([p['id'] for p in self.data['profiles']], [PROFILE])
        self.assertEqual(self.data['bindings'], [{'repository': DEMO, 'stage': 'implement', 'profiles': [PROFILE],
                                                  'catalog_pins': [PIN]}])
        self.assertEqual(sorted(self.pin), ['commit', 'id', 'manifest_sha256', 'repository'])
        self.assertEqual((self.pin['id'], self.pin['repository']), (PIN, di.CATALOG_REPOSITORY))
        self.assertEqual(len(self.data['catalog_pins']), 1)

    def test_the_profile_digest_is_the_checked_in_profile(self):
        self.assertEqual(self.data['profiles'][0]['sha256'], sha256(REPO / 'profiles' / PROFILE / 'profile.json'),
                         'profiles/strong-windows-qemu-whpx/profile.json changed: revise the D1 candidate (the next '
                         'version) and have planning promote it again')

    def test_the_pin_digest_is_the_checked_in_assignment(self):
        self.assertEqual(self.pin['manifest_sha256'], sha256(REPO / di.assignment_path(PIN)),
                         'catalog/assignments/d1-implement.json changed: commit it, pin the new commit and digest in '
                         'a revised candidate, and have planning promote it again')

    def test_the_assignment_at_the_pinned_commit_passes_the_resolvers_check(self):
        if not (REPO / '.git').exists():
            self.skipTest('this copy has no git history: the pinned commit cannot be read here')
        assignment = di.read_assignment(self.pin, di.harness_catalog_sources)
        self.assertEqual(assignment['skills'], [])
        declared = json.loads((REPO / 'profiles' / PROFILE / 'profile.json').read_bytes())
        template = declared['provisioning']['agent_server'][di.STAGE_TEMPLATE_KEY]
        self.assertEqual(assignment['create_template'], {'path': template['path'], 'sha256': template['sha256']})


if __name__ == '__main__':
    unittest.main()
