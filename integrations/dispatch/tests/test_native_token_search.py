"""Tests for the outbound search for the native token (plan leaf E-05.9; decision 0023 section 5), offline.

Run from the repository root, under the tools interpreter (a result bundle is written with Dulwich):

    <tools python> -I -B -m unittest discover -s integrations/dispatch/tests -p test_native_token_search.py -v

Shown: the search finds the token in its raw form and its common encodings (S-03.2's forms, the token's body
after its public prefix included) on records, reports and a result bundle, where a committed copy is deflated in
the bundle's pack (found only once the objects are inflated, deltas applied); its positive controls (S-03.2's, and
the bundle's planted copies) find every planted copy, else the verdict is invalid; a clean result bundle, store
and report directory are not-found, a claim the report limits to the bytes searched; the report carries the
fingerprint and counts only, and one that would hold the token is withheld; the command line reads the token from
its one entry and nothing else, and refuses without an Owner's act, with another fingerprint or a bad surface.
Synthetic tokens only, built at run time; files in a throwaway directory; an in-memory credential provider.
"""
from __future__ import annotations

import base64
import importlib.util
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

CATEGORY = 'unit'

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


S = _load('aieh_native_token_search', HERE.parent / 'native_token_search.py')
NT = S.native_token
NS = _load('native_support', HERE / 'native_support.py')
RA = _load('repository_access', REPO / 'integrations' / 'repository' / 'repository_access.py')
STORE = _load('integration_store', REPO / 'integrations' / 'store' / 'integration_store.py')
TOKEN = NS.token('E-05.9 searched token')


def bundle_of(directory: Path, contents: list) -> bytes:
    """A real result bundle: a repository of one branch whose commits write CONTENTS (bytes, one per commit) to
    notes.txt, written by the repository-access module (Dulwich) and read back as bytes."""
    import dulwich.objects
    import dulwich.repo
    repo = dulwich.repo.Repo.init(str(directory), mkdir=True)
    parent = None
    for n, data in enumerate(contents):
        blob = dulwich.objects.Blob.from_string(data)
        tree = dulwich.objects.Tree()
        tree.add(b'notes.txt', 0o100644, blob.id)
        commit = dulwich.objects.Commit()
        commit.tree, commit.parents = tree.id, [parent] if parent else []
        commit.author = commit.committer = b'E-05.9 test <test@example.invalid>'
        commit.author_time = commit.commit_time = 1_900_000_000 + n
        commit.author_timezone = commit.commit_timezone = 0
        commit.message = f'commit {n}\n'.encode('ascii')
        for obj in (blob, tree, commit):
            repo.object_store.add_object(obj)
        parent = commit.id
    repo.refs[b'refs/heads/main'] = parent
    repo.close()
    destination = directory.parent / f'{directory.name}.bundle'
    RA.open_repository(directory, config='none').write_bundle(['refs/heads/main'], destination)
    return destination.read_bytes()


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-native-search-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)


class Bundle(Fixture):
    def test_a_committed_copy_is_found_only_in_the_inflated_objects(self):
        filler = b''.join(b'line %d of the demo repository\n' % n for n in range(200))
        data = bundle_of(self.tmp / 'leaky', [filler, filler + b'note: ' + TOKEN.encode('ascii') + b'\n'])
        search = S.new_search(TOKEN)
        self.assertFalse(search.holds(data), 'a raw copy: the bundle would not show the pack view is needed')
        objects, incomplete = S.pack_objects(data)
        self.assertEqual(incomplete, [])
        self.assertEqual(sorted(name.split()[-1] for name, _ in objects), ['blob', 'blob', 'commit', 'commit',
                                                                           'tree', 'tree'])
        surface = S.search_bundle(search, 'result-bundle', data)
        self.assertGreater(surface['found'], 0)
        self.assertTrue(all('object' in where for where in surface['where']), surface['where'])
        report = S.report(search, TOKEN)
        self.assertEqual(report['verdict'], 'found')
        self.assertNotIn(TOKEN, json.dumps(report))

    def test_the_bundle_s_positive_control(self):
        control = S.bundle_control(TOKEN)
        self.assertEqual((control['valid'], control['found_whole'], control['raw_holds_a_copy']), (True, 3, False))
        for length in (40, 128, 300, 512):   # split inserts and two-byte copies at every size the shape admits
            with self.subTest(length=length):
                self.assertTrue(S.bundle_control(NS.token('len', length))['valid'])
        # Negative control: a search that cannot apply deltas misses the delta copies, so the control fails.
        with mock.patch.object(S, 'apply_delta', lambda base, delta: base):
            self.assertFalse(S.bundle_control(TOKEN)['valid'])

    def test_deltas_are_applied_as_git_applies_them(self):
        base = bytes(range(256)) * 300
        delta = (S._varint_bytes(len(base)) + S._varint_bytes(60000 + 3) + S._copy(0x1234, 60000)
                 + S._insert(b'xyz'))
        self.assertEqual(S.apply_delta(base, delta), base[0x1234:0x1234 + 60000] + b'xyz')
        whole = S._varint_bytes(len(base)) + S._varint_bytes(0x10000) + b'\x80'   # no size bytes: 0x10000
        self.assertEqual(S.apply_delta(base, whole), base[:0x10000])
        small = S._varint_bytes(len(base)) + S._varint_bytes(5) + S._copy(256, 2) + S._insert(b'abc')
        self.assertEqual(S.apply_delta(base, small), base[256:258] + b'abc')
        for broken in (S._varint_bytes(1) + S._varint_bytes(1) + b'\x00',
                       S._varint_bytes(len(base)) + S._varint_bytes(9) + S._insert(b'abc')):
            with self.subTest(broken=broken[:4]), self.assertRaises(S.BundleError):
                S.apply_delta(base, broken)

    def test_an_unreadable_bundle_is_incomplete_never_not_found(self):
        search = S.new_search(TOKEN)
        for name, data in {'not a bundle': b'PK\x03\x04', 'truncated': S.control_bundle(TOKEN)[:200]}.items():
            with self.subTest(name):
                self.assertFalse(S.search_bundle(search, name.replace(' ', '-'), data)['complete'])


class Verdicts(Fixture):
    def clean_surfaces(self):
        """A clean result bundle, an integration store holding the token's fingerprint, and a report directory."""
        bundle = self.tmp / 'clean.bundle'
        bundle.write_bytes(bundle_of(self.tmp / 'clean', [b'hello\n', b'hello, world\n']))
        store = STORE.open_store(self.tmp / 'integration.sqlite')
        store.reserve('dispatch/test', {'tokenFingerprint': NT.fingerprint(TOKEN)}, actor='e-05.9-test')
        store.close()
        reports = self.tmp / 'reports'
        reports.mkdir()
        (reports / 'report.json').write_text(json.dumps({'native_token': {'tokenFingerprint': NT.fingerprint(TOKEN)}}),
                                             encoding='utf-8')
        return [('bundle', 'bundle', bundle), ('records', 'file', self.tmp / 'integration.sqlite'),
                ('reports', 'tree', reports)]

    def test_clean_surfaces_are_not_found_with_their_limits_stated(self):
        report = S.run(TOKEN, NT.fingerprint(TOKEN), self.clean_surfaces())
        self.assertEqual(report['verdict'], 'not-found', report['statement'])
        self.assertTrue(report['controls']['valid'] and report['bundle_control']['valid'])
        self.assertIn('not proof that the key is absent anywhere else', report['statement'])
        self.assertTrue(report['not_covered'])
        self.assertEqual(report['key'], {'fingerprint': NT.fingerprint(TOKEN), 'held': 'in memory only',
                                         'entry': NT.ENTRY})
        self.assertGreater(report['bytes_searched'], 0)
        self.assertNotIn(TOKEN, json.dumps(report))

    def test_a_planted_copy_is_found_in_each_common_encoding(self):
        """The positive control on real surfaces: one planted copy per form, each in a report file of its own."""
        raw = TOKEN.encode('ascii')
        body = TOKEN[len(NS.PREFIX):].encode('ascii')
        planted = {'raw': raw, 'json': json.dumps({'token': TOKEN}).encode('ascii'), 'hex': raw.hex().encode(),
                   'base64': base64.b64encode(b'x:' + raw), 'base64url': base64.urlsafe_b64encode(raw),
                   'utf-16-le': TOKEN.encode('utf-16-le'), 'body-only': b'Bearer ' + body,
                   'fragment': b'...' + body[3:30] + b'...'}
        for name, data in planted.items():
            with self.subTest(name):
                case = self.tmp / name
                case.mkdir()
                (case / 'report.txt').write_bytes(b'header\n' + data + b'\n')
                report = S.run(TOKEN, NT.fingerprint(TOKEN), [('reports', 'tree', case)])
                self.assertEqual(report['verdict'], 'found')
                self.assertEqual(report['surfaces'][0]['found'] > 0, True)
                self.assertNotIn(TOKEN, json.dumps(report))

    def test_a_missed_control_makes_the_search_invalid(self):
        with mock.patch.object(S, 'bundle_control', lambda token, chunk=None: {'valid': False}):
            report = S.run(TOKEN, NT.fingerprint(TOKEN), self.clean_surfaces())
        self.assertEqual(report['verdict'], 'invalid')

    def test_a_report_that_would_hold_the_token_is_withheld(self):
        search = S.new_search(TOKEN)
        with mock.patch.object(type(search), 'report', lambda self: {'key': {}, 'verdict': 'x', 'leak': TOKEN}):
            with self.assertRaises(S.SearchRefused) as caught:
                S.report(search, TOKEN)
        self.assertEqual(caught.exception.code, 'OUTPUT_WITHHELD')
        self.assertNotIn(TOKEN, str(caught.exception))

    def test_a_fingerprint_search_alone_is_not_the_search(self):
        """A store that holds only the fingerprint is not-found; the token itself is matched, never its fingerprint
        as a stand-in for it."""
        search = S.new_search(TOKEN)
        self.assertFalse(search.holds(NT.fingerprint(TOKEN)))
        self.assertTrue(search.holds(TOKEN))


class CommandLine(Fixture):
    def run_main(self, *argv, provider=None):
        out, err = io.StringIO(), io.StringIO()
        provider = provider or NS.ObservedProvider({NT.ENTRY: (NT.ENTRY_USER, TOKEN),
                                                    'AIEH model provider': ('anthropic', NS.token('other'))})
        code = S.main(list(argv), provider=provider, out=out, err=err)
        return code, out.getvalue(), err.getvalue(), provider

    def test_it_reads_its_one_entry_and_reports_counts(self):
        reports = self.tmp / 'reports'
        reports.mkdir()
        (reports / 'r.json').write_text('{}', encoding='utf-8')
        code, out, err, provider = self.run_main('search', '--owner-act', 'OA-31 (f)', '--expect-fingerprint',
                                                 NT.fingerprint(TOKEN), '--surface', f'reports=tree:{reports}')
        self.assertEqual(code, 0, err)
        self.assertEqual(provider.reads, [NT.ENTRY])
        report = json.loads(out)
        self.assertEqual((report['verdict'], report['owner_act']), ('not-found', 'OA-31 (f)'))
        self.assertNotIn(TOKEN, out + err)
        (reports / 'leak.txt').write_text(TOKEN, encoding='utf-8')
        code, out, _, _ = self.run_main('search', '--owner-act', 'OA-31 (f)', '--expect-fingerprint',
                                        NT.fingerprint(TOKEN), '--surface', f'reports=tree:{reports}')
        self.assertEqual((code, json.loads(out)['verdict']), (1, 'found'))

    def test_refusals(self):
        surface = f'x=tree:{self.tmp}'
        fp = NT.fingerprint(TOKEN)
        cases = {
            'OWNER_ACT_REQUIRED': ('--owner-act', 'bad act!', '--expect-fingerprint', fp, '--surface', surface),
            'FINGERPRINT_MISMATCH': ('--owner-act', 'OA-31', '--expect-fingerprint', 'sha256:' + '0' * 16,
                                     '--surface', surface),
            'FINGERPRINT_INVALID': ('--owner-act', 'OA-31', '--expect-fingerprint', 'x', '--surface', surface),
            'SURFACE_INVALID': ('--owner-act', 'OA-31', '--expect-fingerprint', fp, '--surface', 'x=disk:/'),
            'NATIVE_TOKEN_MISSING': ('--owner-act', 'OA-31', '--expect-fingerprint', fp, '--surface', surface),
        }
        for code, argv in cases.items():
            with self.subTest(code):
                provider = NS.ObservedProvider() if code == 'NATIVE_TOKEN_MISSING' else None
                status, out, err, _ = self.run_main('search', *argv, provider=provider)
                self.assertEqual((status, out), (2, ''))
                self.assertIn(code, err)
                self.assertNotIn(TOKEN, err)


if __name__ == '__main__':
    unittest.main()
