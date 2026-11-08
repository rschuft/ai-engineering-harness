"""Tests for tools/nocloud_seed.py (stdlib unittest).

Run from the repository root:  python -I -B -m unittest discover -s tools/tests -v

Every case writes into its own temporary instance directory. Cases that tamper with a
template work on a temporary copy of profiles/, so the checkout is only read. The
public keys are built here from fixed bytes: they are well-formed ssh-ed25519 public
keys with no private half.

The ISO reader below is written independently of the generator from ECMA-119 and the
Joliet specification; it is the round-trip check (no isoinfo or other host tool).
"""
from pathlib import Path
import base64
import hashlib
import importlib.util
import json
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]
GENERATOR = REPO / 'tools' / 'nocloud_seed.py'
PROFILE = REPO / 'profiles' / 'strong-windows-qemu-whpx'

_spec = importlib.util.spec_from_file_location('nocloud_seed', GENERATOR)
nocloud_seed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(nocloud_seed)

NAME = 'seed-test'
INSTANCE_ID = 'seed-test-00000000-0000-4000-8000-000000000000'
# The sha256 of seed.iso for the fixed input above with key_line(bytes(range(32)),
# 'aieh-test'). It changes only when a template pin or the generator's output changes.
FIXED_INPUT_SHA256 = '9bdcf4209b640c93feaed8bce0bafdd326063598c556f0038530253941cb1c2c'


def key_line(raw32, comment='aieh-test'):
    blob = struct.pack('>I', 11) + b'ssh-ed25519' + struct.pack('>I', len(raw32)) + raw32
    line = 'ssh-ed25519 ' + base64.b64encode(blob).decode('ascii')
    return line + (' ' + comment if comment else '')


KEY_A = key_line(bytes(range(32)))
KEY_B = key_line(bytes(range(1, 33)))


# ---------------------------------------------------------------- independent reader

def le16(b, o):
    return struct.unpack_from('<H', b, o)[0]


def le32(b, o):
    return struct.unpack_from('<I', b, o)[0]


def be16(b, o):
    return struct.unpack_from('>H', b, o)[0]


def be32(b, o):
    return struct.unpack_from('>I', b, o)[0]


def both32(b, o):
    little, big = le32(b, o), be32(b, o + 4)
    assert little == big, f'both-endian mismatch at {o}: {little} != {big}'
    return little


def both16(b, o):
    little, big = le16(b, o), be16(b, o + 2)
    assert little == big, f'both-endian mismatch at {o}: {little} != {big}'
    return little


def read_records(data):
    """Directory records of one directory extent: list of dicts."""
    records, pos = [], 0
    while pos < len(data):
        length = data[pos]
        if length == 0:  # records do not cross a block; skip to the next block
            pos = (pos // 2048 + 1) * 2048
            continue
        rec = data[pos:pos + length]
        id_len = rec[32]
        ident = rec[33:33 + id_len]
        used = 33 + id_len + (1 if id_len % 2 == 0 else 0)
        records.append({
            'length': length, 'ext_attr': rec[1], 'extent': both32(rec, 2),
            'size': both32(rec, 10), 'date': bytes(rec[18:25]), 'flags': rec[25],
            'unit': rec[26], 'gap': rec[27], 'seq': both16(rec, 28), 'id': bytes(ident),
            'system_use': bytes(rec[used:length]),
        })
        pos += length
    return records


def read_iso(image):
    """Parse the image; return a dict describing descriptors, path tables and trees."""
    assert len(image) % 2048 == 0
    out = {'system_area': image[:16 * 2048], 'descriptors': []}
    sector = 16
    while True:
        vd = image[sector * 2048:(sector + 1) * 2048]
        assert vd[1:6] == b'CD001' and vd[6] == 1, f'bad descriptor at {sector}'
        out['descriptors'].append((sector, vd[0]))
        if vd[0] == 255:
            break
        if vd[0] in (1, 2):
            kind = 'primary' if vd[0] == 1 else 'joliet'
            joliet = vd[0] == 2
            dec = (lambda b: b.decode('utf-16-be')) if joliet else (lambda b: b.decode('ascii'))
            root = read_records(vd[156:190])[0]
            pt_size = both32(vd, 132)
            l_pt, m_pt = le32(vd, 140), be32(vd, 148)
            out[kind] = {
                'sector': sector,
                'flags': vd[7],
                'system_id': dec(vd[8:40]),
                'volume_id': dec(vd[40:72]),
                'space': both32(vd, 80),
                'escape': bytes(vd[88:120]),
                'set_size': both16(vd, 120),
                'seq': both16(vd, 124),
                'block': both16(vd, 128),
                'pt_size': pt_size,
                'l_pt': image[l_pt * 2048:l_pt * 2048 + pt_size],
                'm_pt': image[m_pt * 2048:m_pt * 2048 + pt_size],
                'l_pt_loc': l_pt, 'm_pt_loc': m_pt,
                'opt_pt': (le32(vd, 144), be32(vd, 152)),
                'root': root,
                'texts': [dec(vd[a:b]) for a, b in ((190, 318), (318, 446), (446, 574),
                                                    (574, 702))],
                'dates': [bytes(vd[a:a + 17]) for a in (813, 830, 847, 864)],
                'fs_version': vd[881],
                'app_use': bytes(vd[883:1395]),
            }
            entries = read_records(image[root['extent'] * 2048:
                                         root['extent'] * 2048 + root['size']])
            files = {}
            for rec in entries[2:]:
                name = dec(rec['id'])
                files[name] = (rec, image[rec['extent'] * 2048:
                                          rec['extent'] * 2048 + rec['size']])
            out[kind]['entries'] = entries
            out[kind]['files'] = files
        sector += 1
    return out


# ---------------------------------------------------------------- tests

class SeedTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-seed-test-'))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def instance(self, label):
        path = self.tmp / label
        path.mkdir()
        return path

    def key_file(self, line, label='key.pub', raw=None):
        path = self.tmp / label
        path.write_bytes(raw if raw is not None else (line + '\n').encode('ascii'))
        return path

    def generate(self, label, key=KEY_A, profile=PROFILE, instance_id=INSTANCE_ID):
        inst = self.instance(label)
        result = nocloud_seed.generate(profile, inst, NAME, self.key_file(key, label + '.pub'),
                                       instance_id)
        return inst, result

    def copied_profile(self):
        shutil.copytree(REPO / 'profiles', self.tmp / 'repo' / 'profiles')
        return self.tmp / 'repo' / 'profiles' / PROFILE.name

    def tamper(self, profile_dir, template, text, repin):
        root = profile_dir.parents[1]
        target = root / 'profiles' / 'seed' / template
        target.write_bytes(text.encode('utf-8'))
        if repin:
            pj = profile_dir / 'profile.json'
            profile = json.loads(pj.read_text(encoding='utf-8'))
            key = {'user-data.tmpl': 'user-data', 'meta-data.tmpl': 'meta-data',
                   'network-config.yaml': 'network-config'}[template]
            profile['boot_inputs']['seed']['templates'][key]['sha256'] = \
                hashlib.sha256(target.read_bytes()).hexdigest()
            pj.write_text(json.dumps(profile), encoding='utf-8')

    def assertRefused(self, fragment, *args, **kwargs):
        with self.assertRaises(nocloud_seed.Refused) as ctx:
            nocloud_seed.generate(*args, **kwargs)
        self.assertIn(fragment, str(ctx.exception))
        return ctx.exception


class Determinism(SeedTestCase):
    def test_same_inputs_same_bytes(self):
        a, ra = self.generate('a')
        b, rb = self.generate('b')
        self.assertEqual((a / 'seed.iso').read_bytes(), (b / 'seed.iso').read_bytes())
        self.assertEqual(ra['sha256'], rb['sha256'])
        self.assertEqual(ra['sha256'],
                         hashlib.sha256((a / 'seed.iso').read_bytes()).hexdigest())

    def test_fixed_input_digest(self):
        _, result = self.generate('fixed')
        self.assertEqual(result['sha256'], FIXED_INPUT_SHA256)

    def test_cli_in_a_separate_process_gives_the_same_digest(self):
        _, result = self.generate('inproc')
        inst = self.instance('cli')
        key = self.key_file(KEY_A, 'cli.pub')
        proc = subprocess.run(
            [sys.executable, '-I', '-B', str(GENERATOR), '--profile', str(PROFILE),
             '--instance-dir', str(inst), '--instance-name', NAME, '--public-key', str(key),
             '--instance-id', INSTANCE_ID],
            capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        printed = json.loads(proc.stdout)
        self.assertEqual(printed['sha256'], result['sha256'])
        self.assertEqual(printed['instance_id'], INSTANCE_ID)
        self.assertEqual(sorted(p.name for p in inst.iterdir()), ['seed.iso'])

    def test_different_key_different_digest(self):
        _, ra = self.generate('a', KEY_A)
        _, rb = self.generate('b', KEY_B)
        self.assertNotEqual(ra['sha256'], rb['sha256'])

    def test_different_instance_id_different_digest(self):
        _, ra = self.generate('a')
        _, rb = self.generate('b', instance_id=NAME + '-00000000-0000-4000-8000-000000000001')
        self.assertNotEqual(ra['sha256'], rb['sha256'])

    def test_generated_instance_id(self):
        inst = self.instance('fresh')
        result = nocloud_seed.generate(PROFILE, inst, NAME, self.key_file(KEY_A))
        nocloud_seed.check_instance_id(NAME, result['instance_id'])
        self.assertNotEqual(result['instance_id'], nocloud_seed.new_instance_id(NAME))


class RoundTrip(SeedTestCase):
    def setUp(self):
        super().setUp()
        inst, self.result = self.generate('rt')
        self.image = (inst / 'seed.iso').read_bytes()
        self.iso = read_iso(self.image)

    def expected_files(self):
        def text(rel):
            return (REPO / 'profiles' / 'seed' / rel).read_text(encoding='utf-8')
        user = text('user-data.tmpl').replace('{{agent_ssh_public_key}}', KEY_A).replace(
            '{{scratch_device}}', '/dev/disk/by-id/virtio-scratch').replace(
            '{{provision_manifest}}', '')
        meta = text('meta-data.tmpl').replace('{{instance_id}}', INSTANCE_ID).replace(
            '{{instance_name}}', NAME)
        return {'user-data': user.encode(), 'meta-data': meta.encode(),
                'network-config': text('network-config.yaml').encode()}

    def test_descriptor_sequence_has_no_boot_record(self):
        self.assertEqual(self.iso['system_area'], b'\x00' * 16 * 2048)
        self.assertEqual(self.iso['descriptors'], [(16, 1), (17, 2), (18, 255)])

    def test_volume_identifiers_and_geometry(self):
        p, j = self.iso['primary'], self.iso['joliet']
        self.assertEqual(p['volume_id'].rstrip(' '), 'CIDATA')
        self.assertEqual(j['volume_id'].rstrip(' '), 'cidata')
        self.assertEqual(j['escape'][:3], b'%/E')
        self.assertEqual(j['escape'][3:], b'\x00' * 29)
        self.assertEqual(p['escape'], b'\x00' * 32)
        for vd in (p, j):
            self.assertEqual(vd['block'], 2048)
            self.assertEqual(vd['space'] * 2048, len(self.image))
            self.assertEqual((vd['set_size'], vd['seq'], vd['fs_version']), (1, 1, 1))
            self.assertEqual(vd['flags'], 0)
            self.assertEqual(vd['system_id'].strip(' '), '')
            self.assertEqual([t.strip(' ') for t in vd['texts']], ['', '', '', ''])
            self.assertEqual(vd['app_use'], b'\x00' * 512)
            self.assertEqual(vd['opt_pt'], (0, 0))

    def test_dates_are_fixed_or_unset(self):
        fixed, unset = b'1970010100000000\x00', b'0000000000000000\x00'
        for kind in ('primary', 'joliet'):
            vd = self.iso[kind]
            self.assertEqual(vd['dates'], [fixed, fixed, unset, unset])
            for rec in [vd['root']] + vd['entries']:
                self.assertEqual(rec['date'], bytes([70, 1, 1, 0, 0, 0, 0]))

    def test_path_tables_hold_only_the_root(self):
        for kind in ('primary', 'joliet'):
            vd = self.iso[kind]
            root = vd['root']['extent']
            self.assertEqual(vd['pt_size'], 10)
            self.assertEqual(vd['l_pt'], bytes([1, 0]) + struct.pack('<IH', root, 1) + b'\0\0')
            self.assertEqual(vd['m_pt'], bytes([1, 0]) + struct.pack('>IH', root, 1) + b'\0\0')

    def test_joliet_root_holds_exactly_the_three_files(self):
        j = self.iso['joliet']
        self.assertEqual([r['id'] for r in j['entries'][:2]], [b'\x00', b'\x01'])
        for rec in j['entries'][:2]:
            self.assertEqual((rec['extent'], rec['flags']), (j['root']['extent'], 2))
        self.assertEqual(list(j['files']), ['meta-data', 'network-config', 'user-data'])
        expected = self.expected_files()
        for name, (rec, data) in j['files'].items():
            self.assertEqual(rec['flags'], 0)
            self.assertEqual(data, expected[name])

    def test_primary_tree_names_and_shared_extents(self):
        p, j = self.iso['primary'], self.iso['joliet']
        self.assertEqual(list(p['files']), ['META_DAT.;1', 'NETWORK_.;1', 'USER_DAT.;1'])
        for pname, jname in (('META_DAT.;1', 'meta-data'), ('NETWORK_.;1', 'network-config'),
                             ('USER_DAT.;1', 'user-data')):
            self.assertEqual(p['files'][pname][0]['extent'], j['files'][jname][0]['extent'])
            self.assertEqual(p['files'][pname][1], j['files'][jname][1])
        self.assertNotEqual(p['root']['extent'], j['root']['extent'])

    def test_no_rock_ridge_or_extended_attributes(self):
        for kind in ('primary', 'joliet'):
            for rec in [self.iso[kind]['root']] + self.iso[kind]['entries']:
                self.assertEqual(rec['system_use'], b'')
                self.assertEqual((rec['ext_attr'], rec['unit'], rec['gap'], rec['seq']),
                                 (0, 0, 0, 1))

    def test_files_are_utf8_with_lf_line_endings(self):
        for name, (_, data) in self.iso['joliet']['files'].items():
            self.assertNotIn(b'\r', data, name)
            data.decode('utf-8')
            self.assertTrue(data.endswith(b'\n'), name)
            self.assertNotIn(b'{{', data, name)

    def test_meta_data_content(self):
        self.assertEqual(self.iso['joliet']['files']['meta-data'][1],
                         f'instance-id: {INSTANCE_ID}\nlocal-hostname: {NAME}\n'.encode())

    def test_recorded_digests(self):
        self.assertEqual(self.result['sha256'], hashlib.sha256(self.image).hexdigest())
        expected = self.expected_files()
        for name in expected:
            self.assertEqual(self.result['rendered_sha256'][name],
                             hashlib.sha256(expected[name]).hexdigest())


class Refusals(SeedTestCase):
    def test_tampered_template(self):
        profile = self.copied_profile()
        self.tamper(profile, 'network-config.yaml', 'network:\n  version: 1\n', repin=False)
        inst = self.instance('t')
        self.assertRefused('does not match the pinned', profile, inst, NAME,
                           self.key_file(KEY_A), INSTANCE_ID)
        self.assertEqual(list(inst.iterdir()), [])

    def test_unknown_placeholder(self):
        profile = self.copied_profile()
        self.tamper(profile, 'meta-data.tmpl', 'instance-id: {{instance_id}}\n'
                    'local-hostname: {{instance_name}}\nx: {{hostname}}\n', repin=True)
        inst = self.instance('u')
        self.assertRefused("unknown placeholder(s) ['hostname']", profile, inst, NAME,
                           self.key_file(KEY_A), INSTANCE_ID)
        self.assertEqual(list(inst.iterdir()), [])

    def test_leftover_delimiter(self):
        profile = self.copied_profile()
        self.tamper(profile, 'meta-data.tmpl', 'instance-id: {{instance_id}}\n'
                    'local-hostname: {{instance_name}}\nx: {{ unclosed\n', repin=True)
        self.assertRefused('delimiter remains', profile, self.instance('l'), NAME,
                           self.key_file(KEY_A), INSTANCE_ID)

    def test_placeholder_in_untemplated_file(self):
        profile = self.copied_profile()
        self.tamper(profile, 'network-config.yaml', 'network:\n  name: {{instance_name}}\n',
                    repin=True)
        self.assertRefused("network-config: unknown placeholder(s) ['instance_name']",
                           profile, self.instance('n'), NAME, self.key_file(KEY_A),
                           INSTANCE_ID)

    def test_missing_placeholder(self):
        profile = self.copied_profile()
        self.tamper(profile, 'meta-data.tmpl', 'instance-id: {{instance_id}}\n', repin=True)
        self.assertRefused("['instance_name'] missing", profile, self.instance('m'), NAME,
                           self.key_file(KEY_A), INSTANCE_ID)

    def test_malformed_public_keys(self):
        good = KEY_A
        blob = base64.b64decode(good.split()[1])
        rsa = 'ssh-rsa ' + base64.b64encode(struct.pack('>I', 7) + b'ssh-rsa' + b'\0' * 40
                                            ).decode()
        short = 'ssh-ed25519 ' + base64.b64encode(blob[:-1]).decode()
        mislabelled = 'ssh-ed25519 ' + base64.b64encode(
            struct.pack('>I', 7) + b'ssh-rsa' + struct.pack('>I', 32) + bytes(32)).decode()
        cases = {
            'empty': b'',
            'rsa': (rsa + '\n').encode(),
            'two lines': (good + '\n' + good + '\n').encode(),
            'options prefix': ('no-pty ' + good + '\n').encode(),
            'bad base64': b'ssh-ed25519 AAAA*AAA\n',
            'short blob': (short + '\n').encode(),
            'blob of another type': (mislabelled + '\n').encode(),
            'comment with a space': (good + ' two words\n').encode(),
            'comment with a colon space': (good.split(' aieh')[0] + ' a: b\n').encode(),
            'private key': b'-----BEGIN OPENSSH PRIVATE KEY-----\n',
            'non-ascii comment': (good + '\xe9\n').encode('latin-1'),
            'too large': b'ssh-ed25519 ' + b'A' * 5000,
        }
        for label, raw in cases.items():
            with self.subTest(label):
                inst = self.instance(label.replace(' ', '_'))
                self.assertRefused('public key', PROFILE, inst, NAME,
                                   self.key_file('', label.replace(' ', '_') + '.pub', raw),
                                   INSTANCE_ID)
                self.assertEqual(list(inst.iterdir()), [])

    def test_well_formed_key_variants_are_accepted(self):
        for label, line in (('no comment', key_line(bytes(32), '')),
                            ('crlf', None)):
            with self.subTest(label):
                raw = (KEY_A + '\r\n').encode() if line is None else (line + '\n').encode()
                inst = self.instance(label.replace(' ', '_'))
                nocloud_seed.generate(PROFILE, inst, NAME,
                                      self.key_file('', label.replace(' ', '_') + '.pub', raw),
                                      INSTANCE_ID)

    def test_bad_instance_name_and_id(self):
        key = self.key_file(KEY_A)
        self.assertRefused('does not match', PROFILE, self.instance('n1'), 'Bad_Name', key,
                           None)
        self.assertRefused('must be', PROFILE, self.instance('n2'), NAME, key,
                           'other-00000000-0000-4000-8000-000000000000')
        self.assertRefused('is not a UUID', PROFILE, self.instance('n3'), NAME, key,
                           NAME + '-not-a-uuid')
        self.assertRefused('canonical', PROFILE, self.instance('n4'), NAME, key,
                           NAME + '-00000000-0000-4000-8000-00000000000A')

    def test_existing_seed_is_never_overwritten(self):
        inst = self.instance('e')
        (inst / 'seed.iso').write_bytes(b'keep')
        self.assertRefused('never overwritten', PROFILE, inst, NAME, self.key_file(KEY_A),
                           INSTANCE_ID)
        self.assertEqual((inst / 'seed.iso').read_bytes(), b'keep')

    def test_missing_instance_directory(self):
        self.assertRefused('does not exist', PROFILE, self.tmp / 'absent', NAME,
                           self.key_file(KEY_A), INSTANCE_ID)
        self.assertFalse((self.tmp / 'absent').exists())

    def test_cli_refusal_exit_status(self):
        inst = self.instance('c')
        key = self.key_file('', 'bad.pub', b'ssh-rsa AAAA\n')
        proc = subprocess.run(
            [sys.executable, '-I', '-B', str(GENERATOR), '--profile', str(PROFILE),
             '--instance-dir', str(inst), '--instance-name', NAME, '--public-key', str(key),
             '--instance-id', INSTANCE_ID],
            capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(proc.returncode, 1)
        self.assertTrue(proc.stderr.startswith('REFUSED: public key'), proc.stderr)
        self.assertEqual(proc.stdout, '')
        self.assertEqual(list(inst.iterdir()), [])


MANIFEST = (json.dumps({'schema': nocloud_seed.MANIFEST_SCHEMA, 'files': [
    {'name': 'a.deb', 'role': 'deb', 'size': 1, 'sha256': '0' * 64}]}, indent=1) + '\n').encode()


class ProvisionManifest(SeedTestCase):
    """F-04.1b: the third user-data placeholder carries the provisioning manifest."""

    def user_data(self, inst):
        return read_iso((inst / 'seed.iso').read_bytes())['joliet']['files']['user-data'][1]

    def test_ordinary_seed_has_an_empty_manifest(self):
        inst, result = self.generate('o')
        self.assertIsNone(result['provision_manifest_sha256'])
        data = self.user_data(inst)
        self.assertIn(b'    encoding: b64\n    content: ""\n', data)
        self.assertNotIn(b'{{', data)

    def test_manifest_is_written_base64_and_recorded(self):
        inst = self.instance('m')
        result = nocloud_seed.generate(PROFILE, inst, NAME, self.key_file(KEY_A), INSTANCE_ID,
                                       MANIFEST)
        self.assertEqual(result['provision_manifest_sha256'], hashlib.sha256(MANIFEST).hexdigest())
        data = self.user_data(inst).decode('ascii')
        start = data.index('path: /etc/aieh/provision.json')
        line = [l for l in data[start:].splitlines() if l.strip().startswith('content:')][0]
        self.assertEqual(base64.b64decode(line.split('"')[1]), MANIFEST)

    def test_manifest_determinism_and_difference(self):
        a, b, c = self.instance('a'), self.instance('b'), self.instance('c')
        other = MANIFEST.replace(b'a.deb', b'b.deb')
        ra = nocloud_seed.generate(PROFILE, a, NAME, self.key_file(KEY_A, 'a.pub'), INSTANCE_ID, MANIFEST)
        rb = nocloud_seed.generate(PROFILE, b, NAME, self.key_file(KEY_A, 'b.pub'), INSTANCE_ID, MANIFEST)
        rc = nocloud_seed.generate(PROFILE, c, NAME, self.key_file(KEY_A, 'c.pub'), INSTANCE_ID, other)
        self.assertEqual(ra['sha256'], rb['sha256'])
        self.assertNotEqual(ra['sha256'], rc['sha256'])
        self.assertNotEqual(ra['sha256'], FIXED_INPUT_SHA256)

    def test_bad_manifests_refused(self):
        for label, raw, fragment in (
                ('json', b'not json\n', 'not one ASCII JSON'),
                ('schema', b'{"schema": "x"}\n', 'not a ai-engineering-harness'),
                ('list', b'[]\n', 'not a ai-engineering-harness'),
                ('cr', MANIFEST.replace(b'\n', b'\r\n'), 'has CR'),
                ('big', b' ' * (nocloud_seed.MANIFEST_MAX + 1), 'larger than'),
                ('empty', b'', 'empty'),
                ('utf8', MANIFEST.replace(b'a.deb', 'ä.deb'.encode()), 'not one ASCII JSON')):
            inst = self.instance(label)
            self.assertRefused(fragment, PROFILE, inst, NAME, self.key_file(KEY_A, label + '.pub'),
                               INSTANCE_ID, raw)
            self.assertEqual(list(inst.iterdir()), [], label)

    def test_cli_manifest_option(self):
        inst = self.instance('cli')
        manifest = self.tmp / 'manifest.json'
        manifest.write_bytes(MANIFEST)
        proc = subprocess.run(
            [sys.executable, '-I', '-B', str(GENERATOR), '--profile', str(PROFILE),
             '--instance-dir', str(inst), '--instance-name', NAME, '--public-key',
             str(self.key_file(KEY_A)), '--instance-id', INSTANCE_ID,
             '--provision-manifest', str(manifest)],
            capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)['provision_manifest_sha256'],
                         hashlib.sha256(MANIFEST).hexdigest())


if __name__ == '__main__':
    unittest.main()
