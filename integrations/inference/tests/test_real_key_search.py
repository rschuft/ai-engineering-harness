"""The real-key containment search (inference_real_key_search.py, S-03.3 slice 4), in this process only.

The key comes from a fake credential provider standing in for the broker's entry (a synthetic key, or a key of a
provider key's shape made at run time; never a real key, never the real credential store): the command reads it
from the provider's entry "AIEH model provider" only, never from standard input, after every argument is checked
and only under a named Owner act; it refuses unless the key's fingerprint is the one given; it searches the
surfaces with inference_key_search's forms, views and positive controls; and its report, its messages and the
directories it reads hold no copy of the key.
"""
from __future__ import annotations

import ast
import base64
import io
import json
import secrets
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import broker_support as S

CATEGORY = 'unit'
RK = S._load('aieh_inference_real_key_search', S.HERE.parent / 'inference_real_key_search.py')
KS = RK.ks
IB = RK.broker
SOURCE = (S.HERE.parent / 'inference_real_key_search.py').read_text(encoding='utf-8')
ACT = 'OA-12 A1 (synthetic test act)'


def synthetic() -> str:
    return KS.SYNTHETIC_PREFIX + secrets.token_urlsafe(48)[:40]


def provider_shaped() -> str:
    """A key of a provider key's shape (no synthetic prefix), made at run time; not a credential."""
    return '-'.join(('sk', 'ant', 'api03', secrets.token_urlsafe(72)[:93])) + 'AA'


class Provider(S.MemoryProvider):
    name = 'fake-credential-provider'


class Factory:
    """The credential factory: counts its calls; returns a provider holding ENTRIES."""

    def __init__(self, entries=None, fail=None):
        self.entries, self.fail, self.calls = entries, fail, 0

    def __call__(self):
        self.calls += 1
        if self.fail is not None:
            raise self.fail
        return Provider(self.entries)


class NoStdin:
    def __getattr__(self, name):
        raise AssertionError('standard input was touched')


class RealKeySearch(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-real-key-search-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / 'instance'
        (self.root / 'records').mkdir(parents=True)
        (self.root / 'records' / 'acp-qualification.json').write_text('{"result": "PASS"}\n', encoding='utf-8')
        (self.root / 'serial.log').write_bytes(b'boot\n' * 50)

    def run_search(self, key, *, act=ACT, fingerprint=None, surfaces=None, factory=None):
        factory = factory or Factory({IB.ENTRY: (S.PROVIDER, key)})
        argv = ['search', '--owner-act', act, '--expect-fingerprint', fingerprint or KS.fingerprint(key)]
        for surface in surfaces or [f'instance=tree:{self.root}', f'serial=file:{self.root / "serial.log"}']:
            argv += ['--surface', surface]
        out, err = io.StringIO(), io.StringIO()
        with mock.patch('sys.stdin', NoStdin()):
            code = RK.main(argv, out, err, provider_factory=factory)
        return code, out.getvalue(), err.getvalue(), factory

    def assert_no_copy(self, key, *texts):
        for text in texts:
            self.assertFalse(KS.Search(key).holds(text))
            self.assertNotIn(key[-24:], text)

    def test_the_key_of_the_brokers_entry_is_searched_in_memory_and_never_shown(self):
        for key in (synthetic(), provider_shaped()):
            with self.subTest(shape=key[:4]):
                before = sorted((p.relative_to(self.tmp), p.stat().st_size) for p in self.tmp.rglob('*'))
                code, out, err, factory = self.run_search(key)
                self.assertEqual(code, 0, err)
                self.assertEqual(factory.calls, 1)
                report = json.loads(out)
                self.assertEqual((report['format'], report['search_format'], report['verdict']),
                                 (RK.FORMAT, KS.FORMAT, 'not-found'))
                self.assertEqual(report['key']['fingerprint'], KS.fingerprint(key))
                self.assertEqual((report['key']['entry'], report['key']['source'], report['key']['owner_act']),
                                 ('AIEH model provider', 'fake-credential-provider', ACT))
                self.assertIn('never from standard input', report['key']['read'])
                self.assertEqual(report['controls']['valid'], True)
                self.assertEqual(report['controls']['cases'], 191)
                self.assertEqual([s['label'] for s in report['surfaces']], ['instance', 'serial'])
                self.assertTrue(all(s['complete'] and s['bytes_total'] > 0 for s in report['surfaces']))
                self.assertIn('controls valid (191 cases)', err)
                self.assertIn(f"under '{ACT}'", err)
                self.assert_no_copy(key, out, err)
                after = sorted((p.relative_to(self.tmp), p.stat().st_size) for p in self.tmp.rglob('*'))
                self.assertEqual(after, before, 'the search wrote something')

    def test_a_planted_copy_is_found_on_each_surface_kind(self):
        key = provider_shaped()
        k = key.encode()
        plants = {'records/b64.txt': base64.b64encode(b'user:' + k),
                  'records/wide.txt': ('key=' + key).encode('utf-16-le'),
                  'records/hex.txt': k.hex().encode(),
                  'records/fragment.txt': b'...' + k[30:60] + b'...'}
        for name, data in plants.items():
            with self.subTest(plant=name):
                path = self.root / name
                path.write_bytes(data)
                code, out, err, _ = self.run_search(key)
                path.unlink()
                self.assertEqual(code, 1, err)
                report = json.loads(out)
                self.assertEqual(report['verdict'], 'found')
                self.assertEqual(report['surfaces'][0]['where'], [name])
                self.assert_no_copy(key, out, err)
        database = self.root / 'records' / 'store.sqlite'
        connection = sqlite3.connect(database)
        with connection:
            connection.execute('CREATE TABLE t (v TEXT)')
            connection.execute('INSERT INTO t VALUES (?)', (json.dumps({'provider_key': key}),))
        connection.close()
        code, out, err, _ = self.run_search(key, surfaces=[f'store=file:{database}'])
        self.assertEqual((code, json.loads(out)['verdict']), (1, 'found'))
        self.assert_no_copy(key, out, err)

    def test_refusals_before_the_provider_is_asked(self):
        key = synthetic()
        surface = f'instance=tree:{self.root}'
        for act, fingerprint, surfaces, code in (
                ('', None, [surface], 'OWNER_ACT_REQUIRED'),
                (' A1', None, [surface], 'OWNER_ACT_REQUIRED'),
                ('A1' + 'x' * 64, None, [surface], 'OWNER_ACT_REQUIRED'),
                ('A1;rm', None, [surface], 'OWNER_ACT_REQUIRED'),
                (ACT, 'sha256:XYZ', [surface], 'FINGERPRINT_INVALID'),
                (ACT, None, ['r=disk:/x'], 'SURFACE_INVALID'),
                (ACT, None, [surface, surface], 'SURFACE_INVALID')):
            with self.subTest(code=code, act=act):
                status, out, err, factory = self.run_search(key, act=act, fingerprint=fingerprint, surfaces=surfaces)
                self.assertEqual((status, out), (2, ''), err)
                self.assertIn(code, err)
                self.assertEqual(factory.calls, 0, 'the provider was asked before the arguments were checked')
        for argv in (['search', '--expect-fingerprint', KS.fingerprint(key), '--surface', surface],
                     ['search', '--owner-act', ACT, '--surface', surface], []):
            with self.subTest(argv=argv), mock.patch('sys.stderr', new_callable=io.StringIO), \
                    self.assertRaises(SystemExit) as caught:
                RK.main(argv, io.StringIO(), io.StringIO(), provider_factory=Factory(fail=AssertionError('asked')))
            self.assertEqual(caught.exception.code, 2)

    def test_the_provider_and_its_entry_refused_without_repeating_the_key(self):
        key, other = provider_shaped(), provider_shaped()
        for factory, code in ((Factory(fail=OSError(f'backend said {key}')), 'KEY_PROVIDER_FAILED'),
                              (Factory({}), 'KEY_ENTRY_ABSENT'),
                              (Factory({IB.ENTRY: (S.PROVIDER, '')}), 'KEY_ENTRY_ABSENT'),
                              (Factory({IB.ENTRY: key}), 'KEY_ENTRY_ABSENT'),
                              (Factory({'another entry': (S.PROVIDER, key)}), 'KEY_ENTRY_ABSENT'),
                              (Factory({IB.ENTRY: (S.PROVIDER, other)}), 'FINGERPRINT_MISMATCH'),
                              (Factory({IB.ENTRY: (S.PROVIDER, 'short')}), 'FINGERPRINT_MISMATCH')):
            with self.subTest(code=code):
                status, out, err, _ = self.run_search(key, factory=factory)
                self.assertEqual((status, out), (2, ''), err)
                self.assertIn(code, err)
                self.assert_no_copy(key, err)
                self.assert_no_copy(other, err)
        self.assertIn('OSError', self.run_search(key, factory=Factory(fail=OSError(key)))[2])

    def test_a_report_that_would_hold_the_key_is_withheld(self):
        key = provider_shaped()
        status, out, err, _ = self.run_search(key, surfaces=[f'{key[-30:]}=tree:{self.root}'])
        self.assertEqual((status, out), (1, ''))
        self.assertIn('OUTPUT_WITHHELD', err)
        self.assert_no_copy(key, err)
        with mock.patch.object(KS, 'run', lambda k, e, s: {'format': KS.FORMAT, 'key': {'fingerprint': e},
                                                           'echo': k[::-1][::-1]}):
            status, out, err, _ = self.run_search(key)
        self.assertEqual((status, out), (1, ''))
        self.assertIn('OUTPUT_WITHHELD', err)

    def test_it_is_the_brokers_entry_and_factory_and_reads_writes_nothing_else(self):
        self.assertEqual(RK.broker.ENTRY, 'AIEH model provider')
        tree = ast.parse(SOURCE)
        main = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'main')
        self.assertIn('provider_factory or broker.credentials.select_provider', ast.unparse(main))
        reader = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'read_entry_key')
        self.assertIn('provider.get(broker.ENTRY)', ast.unparse(reader))
        attributes = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        self.assertFalse(attributes & {'stdin', 'environ', 'getenv', 'environb', 'set', 'delete'})
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
        names = {getattr(c.func, 'id', None) for c in calls} | {getattr(c.func, 'attr', None) for c in calls}
        self.assertFalse(names & {'print', 'open', 'write_text', 'write_bytes', 'mkdir', 'unlink', 'connect',
                                  'urlopen', 'socket', 'HTTPConnection', 'HTTPSConnection', 'basicConfig'})
        writes = sorted(ast.unparse(c.func) for c in calls if getattr(c.func, 'attr', None) == 'write')
        self.assertEqual(writes, ['err.write', 'err.write', 'out.write'])
        imported = {a.name.split('.')[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        self.assertFalse(imported & {'socket', 'http', 'urllib', 'subprocess', 'logging', 'tempfile', 'ssl'})


if __name__ == '__main__':
    unittest.main()
