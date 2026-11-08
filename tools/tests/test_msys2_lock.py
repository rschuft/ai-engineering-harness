"""Tests for tools/msys2_lock.py (stdlib unittest).

Run from the repository root:  python -I -B -m unittest discover -s tools/tests -v

Archives are built in a temporary directory with tarfile. Most cases read them
directly (pax_stream is replaced by a plain stream reader); one case runs them
through Windows' built-in tar.exe when it is present. Nothing touches the network.
"""
from pathlib import Path
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
import unittest
import unittest.mock

CATEGORY = 'unit'

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / 'tools' / 'msys2_lock.py'
_spec = importlib.util.spec_from_file_location('msys2_lock', TOOL)
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)


def pkg(name, version='1.0-1', depends=(), provides=(), conflicts=(), replaces=()):
    return {'name': name, 'version': version, 'filename': f'{name}-{version}-any.pkg.tar.zst',
            'sha256': '0' * 64, 'csize': 1, 'license': 'MIT', 'depends': list(depends),
            'provides': list(provides), 'conflicts': list(conflicts), 'replaces': list(replaces)}


def db_of(*packages):
    return {p['name']: p for p in packages}


def build_tar(path, entries):
    """entries: (name, kind, data_or_target). kind in file, dir, symlink, hardlink, chr, fifo."""
    with tarfile.open(path, 'w', format=tarfile.PAX_FORMAT) as tf:
        for name, kind, payload in entries:
            info = tarfile.TarInfo(name)
            data = None
            if kind == 'file':
                data = payload if isinstance(payload, bytes) else payload.encode()
                info.size = len(data)
            elif kind == 'dir':
                info.type = tarfile.DIRTYPE
            elif kind == 'symlink':
                info.type, info.linkname = tarfile.SYMTYPE, payload
            elif kind == 'hardlink':
                info.type, info.linkname = tarfile.LNKTYPE, payload
            elif kind == 'chr':
                info.type = tarfile.CHRTYPE
            elif kind == 'fifo':
                info.type = tarfile.FIFOTYPE
            tf.addfile(info, io.BytesIO(data) if data is not None else None)


def scan_entries(entries, tmp):
    path = Path(tmp) / 'x.tar'
    build_tar(path, entries)
    with open(path, 'rb') as fh, tarfile.open(fileobj=fh, mode='r|') as tf:
        return m.scan_archive(tf)


@contextlib.contextmanager
def plain_stream(archive):
    with open(archive, 'rb') as fh, tarfile.open(fileobj=fh, mode='r|') as tf:
        yield tf


def sha(data):
    return hashlib.sha256(data).hexdigest()


class VercmpTests(unittest.TestCase):
    def test_libalpm_cases(self):
        cases = [('1.5.0', '1.5.0', 0), ('1.5.1', '1.5.0', 1), ('1.5.1', '1.5', 1),
                 ('1.5', '1.5.1', -1), ('1.5a', '1.5', -1), ('1.5b', '1.5a', 1),
                 ('1.5.a', '1.5', 1), ('1.0rc', '1.0', -1), ('1.0alpha', '1.0b', -1),
                 ('1.010', '1.9', 1), ('1.01', '1.1', 0), ('1.0', '1..0', -1),
                 ('1:1.0', '2.0', 1), ('1.0-1', '1.0-2', -1), ('1.0', '1.0-2', 0),
                 ('2.042u+1.062i+1.026vf-1', '2.042u+1.062i+1.026vf-1', 0),
                 ('11.1.3-1', '11.1.2-1', 1), ('2026f-1', '2026e-1', 1)]
        for a, b, want in cases:
            with self.subTest(a=a, b=b):
                self.assertEqual(m.vercmp(a, b), want)
                self.assertEqual(m.vercmp(b, a), -want)

    def test_satisfies_versions_and_provides(self):
        p = pkg('foo', '2.0-1', provides=['bar=2.0', 'baz'])
        self.assertTrue(m.satisfies(p, 'foo>=1.5'))
        self.assertFalse(m.satisfies(p, 'foo<2.0'))
        self.assertTrue(m.satisfies(p, 'bar>1'))
        self.assertTrue(m.satisfies(p, 'baz'))
        self.assertFalse(m.satisfies(p, 'baz>=1'))  # an unversioned provision meets no version


class ResolverTests(unittest.TestCase):
    def test_replaced_package_is_never_chosen(self):
        # The defect F-03.2.1a shipped: sqlite3 is replaced by sqlite, which provides it.
        db = db_of(pkg('root', depends=['python', 'nss']),
                   pkg('python', depends=['sqlite3']), pkg('nss', depends=['sqlite']),
                   pkg('sqlite', '3.54.1-2', provides=['sqlite3=3.54.1'],
                       conflicts=['sqlite3'], replaces=['sqlite3']),
                   pkg('sqlite3', '3.54.1-1', provides=['sqlite=3.54.1']))
        names, log = m.resolve(db, ['root'])
        self.assertEqual(names, ['nss', 'python', 'root', 'sqlite'])
        self.assertTrue(any('replaced by sqlite' in line for line in log), log)

    def test_conflicting_provider_drops_the_provided(self):
        # b is reached first by name, then a, which conflicts with and provides b.
        db = db_of(pkg('root', depends=['b', 'a']), pkg('a', provides=['b'], conflicts=['b']),
                   pkg('b'))
        names, log = m.resolve(db, ['root'])
        self.assertEqual(names, ['a', 'root'])
        self.assertTrue(any('b dropped' in line for line in log), log)

    def test_unresolvable_conflict_stops(self):
        db = db_of(pkg('root', depends=['a', 'b']), pkg('a', conflicts=['b']), pkg('b'))
        with self.assertRaisesRegex(m.Stop, 'unresolvable conflict'):
            m.resolve(db, ['root'])

    def test_ambiguous_provider_stops(self):
        db = db_of(pkg('root', depends=['virt']), pkg('a', provides=['virt']),
                   pkg('b', provides=['virt']))
        with self.assertRaisesRegex(m.Stop, 'ambiguous'):
            m.resolve(db, ['root'])

    def test_version_constraint_unsatisfiable(self):
        db = db_of(pkg('root', depends=['lib>=2.0']), pkg('lib', '1.9-1'))
        with self.assertRaisesRegex(m.Stop, 'unsatisfiable'):
            m.resolve(db, ['root'])

    def test_desc_parsing(self):
        text = ('%NAME%\nfoo\n\n%VERSION%\n1.0-1\n\n%LICENSE%\nMPL\nGPL\n\n'
                '%DEPENDS%\nbar>=1\nbaz\n\n%PROVIDES%\nqux=1.0\n\n')
        p = m.package_from_desc(m.parse_desc(text))
        self.assertEqual((p['name'], p['version'], p['license']), ('foo', '1.0-1', 'MPL GPL'))
        self.assertEqual(p['depends'], ['bar>=1', 'baz'])
        self.assertEqual(p['provides'], ['qux=1.0'])


class EntryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def problems(self, entries):
        return {p['name']: p['problems'] for p in scan_entries(entries, self.tmp)[1]}

    def test_clean_package(self):
        entries, problems = scan_entries([('.PKGINFO', 'file', 'x'), ('ucrt64', 'dir', None),
                                          ('ucrt64/bin/a.exe', 'file', 'abc')], self.tmp)
        self.assertEqual(problems, [])
        self.assertTrue(entries[0]['meta'])
        self.assertEqual(entries[2]['sha256'], sha(b'abc'))

    def test_unsafe_names(self):
        bad = ['../evil', 'ucrt64/../../evil', '/abs', 'C:/x', 'ucrt64/a:stream',
               'ucrt64/a\\b', 'ucrt64/NUL.txt', 'ucrt64/com1', 'ucrt64/dot.',
               'ucrt64/.INSTALL', 'ucrt64/./x']
        found = self.problems([(n, 'file', 'x') for n in bad])
        for name in bad:
            self.assertIn(name.rstrip('/'), found, name)

    def test_link_and_device_types(self):
        found = self.problems([('ucrt64/a', 'file', 'x'), ('ucrt64/s', 'symlink', 'a'),
                               ('ucrt64/c', 'chr', None), ('ucrt64/f', 'fifo', None)])
        self.assertEqual(found['ucrt64/s'], ['symlink'])
        self.assertIn('entry type chardev', found['ucrt64/c'])
        self.assertIn('entry type fifo', found['ucrt64/f'])

    def test_hardlink_policy(self):
        entries, problems = scan_entries([('ucrt64/a', 'file', 'data'),
                                          ('ucrt64/b', 'hardlink', 'ucrt64/a')], self.tmp)
        self.assertEqual(problems, [])
        self.assertEqual(entries[1]['sha256'], sha(b'data'))
        found = self.problems([('ucrt64/b', 'hardlink', 'ucrt64/later'),
                               ('ucrt64/later', 'file', 'x'),
                               ('ucrt64/c', 'hardlink', '../outside'),
                               ('usr/d', 'hardlink', 'ucrt64/later')])
        self.assertTrue(any('not an earlier regular file' in p for p in found['ucrt64/b']))
        self.assertTrue(any('target' in p for p in found['ucrt64/c']))
        self.assertTrue(any('outside ucrt64/' in p for p in found['usr/d']))

    def test_overlaps(self):
        per = {'a': [{'name': 'ucrt64', 'kind': 'dir'}, {'name': 'ucrt64/x', 'kind': 'file'},
                     {'name': 'ucrt64/Y', 'kind': 'file'}, {'name': 'ucrt64/z', 'kind': 'dir'}],
               'b': [{'name': 'ucrt64', 'kind': 'dir'}, {'name': 'ucrt64/x', 'kind': 'file'},
                     {'name': 'ucrt64/y', 'kind': 'hardlink'}, {'name': 'ucrt64/z', 'kind': 'file'}],
               'c': [{'name': '.PKGINFO', 'kind': 'file', 'meta': True}]}
        paths = sorted(f['path'] for f in m.overlap_findings(per))
        self.assertEqual(paths, ['ucrt64/Y', 'ucrt64/x', 'ucrt64/z'])

    def test_lock_policy(self):
        entries = [{'name': 'ucrt64/a', 'kind': 'file'}, {'name': 'ucrt64/b', 'kind': 'hardlink'}]
        ok = {'filename': 'p', 'hardlinks': 1, 'link_policy': m.LINK_POLICY}
        self.assertEqual(m.check_lock_policy(ok, entries, []), [])
        self.assertTrue(m.check_lock_policy({'filename': 'p'}, entries, []))
        sym = [{'name': 'ucrt64/s', 'kind': 'symlink'}]
        sym_problem = [{'name': 'ucrt64/s', 'kind': 'symlink', 'problems': ['symlink']}]
        self.assertTrue(m.check_lock_policy({'filename': 'p'}, sym, sym_problem))
        self.assertEqual(m.check_lock_policy({'filename': 'p', 'extract': False}, sym,
                                             sym_problem), [])


class InstallTests(unittest.TestCase):
    """validate, extract and verify on small uncompressed archives."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.dl = self.tmp / 'dl'
        self.dl.mkdir()
        self.prefix = self.tmp / 'state' / 'prefix'
        patcher = unittest.mock.patch.object(m, 'pax_stream', plain_stream)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.packages = {
            'one': [('.PKGINFO', 'file', 'meta'), ('.INSTALL', 'file', 'script'),
                    ('ucrt64', 'dir', None), ('ucrt64/bin', 'dir', None),
                    ('ucrt64/bin/a.exe', 'file', 'program'),
                    ('ucrt64/bin/b.exe', 'hardlink', 'ucrt64/bin/a.exe')],
            'two': [('.PKGINFO', 'file', 'meta'), ('ucrt64', 'dir', None),
                    ('ucrt64/share', 'dir', None), ('ucrt64/share/data', 'file', 'data')],
            'links': [('ucrt64/share/l', 'symlink', 'data')],
        }

    def make_lock(self, **extra):
        packages = []
        for name, entries in self.packages.items():
            path = self.dl / f'{name}-1.0-1-any.pkg.tar.zst'
            build_tar(path, entries)
            entry = {'name': name, 'version': '1.0-1', 'filename': path.name,
                     'sha256': m.sha256_file(path), 'license': 'MIT'}
            entry.update(extra.get(name, {}))
            packages.append(entry)
        return {'repository': {'base_url': 'https://example.invalid/'}, 'packages': packages,
                'extracted_files': {'ucrt64/bin/a.exe': sha(b'program')}}

    def lock_ok(self):
        return self.make_lock(one={'hardlinks': 1, 'link_policy': m.LINK_POLICY},
                              links={'extract': False})

    def test_install_materialises_hardlinks_and_verifies(self):
        lock, report = self.lock_ok(), {}
        scans, manifest = m.validate(lock, self.dl, self.prefix, report)
        m.extract(lock, self.dl, self.prefix, scans, report)
        m.verify(lock, self.prefix, manifest, report)
        self.assertEqual(report['extract']['materialised_hardlinks'], {'one': 1})
        b = self.prefix / 'ucrt64' / 'bin' / 'b.exe'
        self.assertEqual(b.read_bytes(), b'program')
        self.assertEqual(os.lstat(b).st_nlink, 1)
        self.assertFalse((self.prefix / '.PKGINFO').exists())
        self.assertFalse((self.prefix / '.INSTALL').exists())
        self.assertFalse((self.prefix / 'ucrt64' / 'share' / 'l').exists())
        self.assertEqual(report['verify']['installed_files'], 3)

    def test_unrecorded_hardlink_stops_before_extraction(self):
        lock = self.make_lock(links={'extract': False})
        with self.assertRaisesRegex(m.Stop, 'validation findings'):
            m.validate(lock, self.dl, self.prefix, {})
        self.assertFalse(self.prefix.exists())

    def test_symlink_in_extracted_package_stops(self):
        lock = self.make_lock(one={'hardlinks': 1, 'link_policy': m.LINK_POLICY})
        report = {}
        with self.assertRaises(m.Stop):
            m.validate(lock, self.dl, self.prefix, report)
        self.assertTrue(any('symlinks in an extracted package' in f
                            for f in report['validate']['findings']))

    def test_overlap_stops(self):
        self.packages['two'].append(('ucrt64/bin/a.exe', 'file', 'other'))
        report = {}
        with self.assertRaises(m.Stop):
            m.validate(self.lock_ok(), self.dl, self.prefix, report)
        self.assertEqual(report['validate']['overlaps'], 1)

    def test_existing_prefix_stops(self):
        lock, report = self.lock_ok(), {}
        scans, _ = m.validate(lock, self.dl, self.prefix, report)
        self.prefix.mkdir(parents=True)
        with self.assertRaisesRegex(m.Stop, 'already exists'):
            m.extract(lock, self.dl, self.prefix, scans, report)

    def test_archive_changed_after_validation_stops(self):
        lock, report = self.lock_ok(), {}
        scans, _ = m.validate(lock, self.dl, self.prefix, report)
        build_tar(self.dl / lock['packages'][1]['filename'],
                  [('ucrt64', 'dir', None), ('ucrt64/share', 'dir', None),
                   ('ucrt64/share/data', 'file', 'tampered')])
        with self.assertRaises(m.Stop):
            m.extract(lock, self.dl, self.prefix, scans, report)

    def test_extra_file_fails_verification(self):
        lock, report = self.lock_ok(), {}
        scans, manifest = m.validate(lock, self.dl, self.prefix, report)
        m.extract(lock, self.dl, self.prefix, scans, report)
        (self.prefix / 'ucrt64' / 'extra').write_bytes(b'x')
        with self.assertRaisesRegex(m.Stop, 'verification failed'):
            m.verify(lock, self.prefix, manifest, report)
        self.assertEqual(report['verify']['extra'], ['ucrt64/extra'])

    def test_fetch_refuses_non_https(self):
        lock = {'repository': {'base_url': 'http://example.invalid/'}, 'packages': []}
        with self.assertRaisesRegex(m.Stop, 'https'):
            m.fetch(lock, self.dl, {})


@unittest.skipUnless(m.TAR.is_file(), 'Windows built-in tar.exe not present')
class TarExeStreamTests(unittest.TestCase):
    category = 'integration'

    def test_pax_stream_reads_through_tar_exe(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        path = tmp / 'p.tar'
        build_tar(path, [('ucrt64', 'dir', None), ('ucrt64/a', 'file', 'x' * 5000),
                         ('ucrt64/b', 'hardlink', 'ucrt64/a')])
        with m.pax_stream(path) as tf:
            entries, problems = m.scan_archive(tf)
        self.assertEqual(problems, [])
        self.assertEqual([e['kind'] for e in entries], ['dir', 'file', 'hardlink'])
        self.assertEqual(entries[2]['sha256'], sha(b'x' * 5000))


if __name__ == '__main__':
    unittest.main()
