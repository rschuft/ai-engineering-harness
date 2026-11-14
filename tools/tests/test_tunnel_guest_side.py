"""The guest side of the native profile's provider tunnel is S-03.2's composition, byte for byte
(plan leaf E-05.10; decision 0023 section 4.1), offline: nothing is written, no guest is started.

The native profile changes only the forward's host-side target (the tunnel instead of the broker): the
seed an opted-in guest is created with, and every declared rule the guest enforces (one sshd PermitListen,
one container-guard ACCEPT, an empty egress-guard allowlist, DNS refused), are those S-03.2 declared. The
digests below were computed at baebf8d, the last commit before E-05.10, from the same functions, and the
profile's tunnel endpoint (class provider-tunnel) must leave them unchanged.
"""
import copy
import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path

CATEGORY = 'contract'

REPO = Path(__file__).resolve().parents[2]
PROFILE_DIR = REPO / 'profiles' / 'strong-windows-qemu-whpx'
sys.path.insert(0, str(Path(__file__).resolve().parent))
import module_code  # noqa: E402
guest = module_code.load('guest', REPO / 'tools' / 'guest.py')


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


nocloud_seed = _load('nocloud_seed_tunnel_side', REPO / 'tools' / 'nocloud_seed.py')
seed_tests = _load('seed_tests_tunnel_side', REPO / 'tools' / 'tests' / 'test_nocloud_seed.py')

# Computed at baebf8d (S-03.2's composition as built, before E-05.10's records): the inference seed of the
# fixed input of test_nocloud_seed (user-data and seed.iso), and the declared guest rules (declared_rules).
S032_USER_DATA_SHA256 = '4ea96a9eb3affa5eaf96f849491e90adf27ea298a9bd25a205ec5b53e1bb6bd7'
S032_SEED_ISO_SHA256 = '3779e1ae6bed6fbef4b39d69a1b9d16720a250961c880b3d6550c920bb26851b'
S032_RULES_SHA256 = '9af48a1e91436f9e6bdeb61828a7c18be5297179d4877e11088c1446e7363015'
OPTED = {'inference': {'composition': 'inference', 'status': 'planned'}}


def profile_json():
    return json.loads((PROFILE_DIR / 'profile.json').read_text(encoding='utf-8'))


def rendered_seed(profile_dir=PROFILE_DIR):
    """(user-data, seed.iso) of the fixed input with the inference composition."""
    profile, root = nocloud_seed.load_profile(profile_dir)
    templates = nocloud_seed.read_templates(profile, root)
    composed, _ = nocloud_seed.compose_templates(profile, root, templates, ('inference',))
    values = {'agent_ssh_public_key': nocloud_seed.parse_public_key(seed_tests.KEY_A),
              'scratch_device': nocloud_seed.scratch_device(profile),
              'provision_manifest': nocloud_seed.provision_manifest_value(seed_tests.inference_manifest()),
              'instance_id': seed_tests.INSTANCE_ID, 'instance_name': seed_tests.NAME}
    rendered = nocloud_seed.render(composed, values)
    return rendered['user-data'], nocloud_seed.build_iso(rendered)


def declared_rules(profile):
    """Every rule the guest enforces for an opted-in instance, as declared: the inference endpoint, the
    composition (sshd, the container guard's allow, daemon.json, the forward's options), the admission
    network (the container guard's and the egress guard's chains and allowlist), the container guard's
    rules per family as guest.py composes them, and the daemon.json an opted-in guest gets."""
    network = profile['network']
    endpoint = [e for e in network['endpoints'] if e.get('class') == 'inference']
    admission = guest.admission_config(profile).get('network')
    return {'inference_endpoint': endpoint, 'inference_composition': network['inference_composition'],
            'admission_network': admission,
            'guard_rules': {tool: guest.guard_rules_for(profile, OPTED, tool) for tool in ('iptables', 'ip6tables')},
            'daemon_json': guest.declared_daemon_json(profile, True)}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


class GuestSideIdentity(unittest.TestCase):
    """E-05.10's proof: the guest side is byte-identical to S-03.2's composition."""

    def test_the_seed_is_s032s(self):
        user_data, iso = rendered_seed()
        self.assertEqual(hashlib.sha256(user_data).hexdigest(), S032_USER_DATA_SHA256)
        self.assertEqual(hashlib.sha256(iso).hexdigest(), S032_SEED_ISO_SHA256)

    def test_the_declared_rules_are_s032s(self):
        self.assertEqual(digest(declared_rules(profile_json())), S032_RULES_SHA256)

    def test_the_four_named_facts(self):
        """One sshd PermitListen, one container-guard ACCEPT, an empty egress-guard allowlist, DNS refused."""
        profile = profile_json()
        comp = profile['network']['inference_composition']
        self.assertEqual([d for d in comp['sshd']['directives'] if d.startswith('PermitListen')],
                         ['PermitListen 172.17.0.1:8090'])
        rules = guest.guard_rules_for(profile, OPTED, 'iptables')
        self.assertEqual([r for r in rules if r.endswith('-j ACCEPT')],
                         ['-d 172.17.0.1/32 -i docker0 -p tcp -m tcp --dport 8090 -j ACCEPT'])
        self.assertEqual([r for r in guest.guard_rules_for(profile, OPTED, 'ip6tables') if r.endswith('-j ACCEPT')],
                         [])
        egress = guest.admission_config(profile)['network']['egress_guard']
        self.assertEqual(egress['allowlist'], [])
        self.assertEqual(guest.declared_daemon_json(profile, True)['dns'], ['172.17.0.1'])
        user_data, _ = rendered_seed()
        self.assertEqual(user_data.count(b'PermitListen'), 1)

    def test_the_tunnel_endpoint_is_outside_the_guest_side(self):
        """The provider-tunnel endpoint names the inference endpoint's guest listener and changes nothing the
        guest is given: without it the seed and the rules are the same."""
        profile = profile_json()
        tunnel = [e for e in profile['network']['endpoints'] if e.get('class') == 'provider-tunnel']
        self.assertEqual(len(tunnel), 1)
        inference = [e for e in profile['network']['endpoints'] if e.get('class') == 'inference'][0]
        self.assertEqual((tunnel[0]['guest_address'], tunnel[0]['guest_port']),
                         (inference['guest_address'], inference['guest_port']))
        without = copy.deepcopy(profile)
        without['network']['endpoints'] = [e for e in without['network']['endpoints']
                                           if e.get('class') != 'provider-tunnel']
        self.assertEqual(digest(declared_rules(without)), digest(declared_rules(profile)))


if __name__ == '__main__':
    unittest.main()
