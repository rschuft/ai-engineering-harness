"""The provider-key containment search (inference_key_search.py, S-03.2 slice 5), in this process only.

Its forms, views and surfaces; its positive controls, each of which must find a planted copy (and fail when the view
it controls is broken); its verdicts; its command line, which reads the key from standard input only and prints,
logs and writes nothing that holds the key. Every key is a synthetic key made at run time; every planted copy is
in a temporary directory of this test or in memory.
"""
from __future__ import annotations

import ast
import base64
import binascii
import builtins
import gzip
import io
import json
import os
import re
import secrets
import shutil
import sqlite3
import tarfile
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

import broker_support as S

CATEGORY = 'unit'
KS = S._load('aieh_inference_key_search', S.HERE.parent / 'inference_key_search.py')
IQ = S._load('aieh_inference_qualification', S.HERE.parent / 'inference_qualification.py')
SOURCE = (S.HERE.parent / 'inference_key_search.py').read_text(encoding='utf-8')
SMALL = 4096          # a small read chunk, so that a straddle costs little


def synthetic(length: int = 40) -> str:
    """A synthetic qualification key of LENGTH body characters, made at run time."""
    return KS.SYNTHETIC_PREFIX + secrets.token_urlsafe(length * 2)[:length]


class Pipe(io.BytesIO):
    """Standard input as a pipe of bytes (or a terminal)."""

    def __init__(self, data: bytes = b'', tty: bool = False):
        super().__init__(data)
        self.tty = tty

    def isatty(self):
        return self.tty

    @property
    def buffer(self):
        return self


def substrings(key: str, size: int = 24):
    return [key[i:i + size] for i in range(len(key) - size + 1)]


class TestForms(unittest.TestCase):
    def test_the_needles_are_the_standard_encodings_of_the_key_and_its_body(self):
        key = synthetic(40)
        body = key[len(KS.SYNTHETIC_PREFIX):]
        table = KS.needles(key)
        by_label = {label: needle for needle, labels in table.items() for label in labels}
        for part, text in (('key', key), ('body', body)):
            value = text.encode()
            self.assertEqual(by_label[f'{part}/raw'], value)
            self.assertEqual(by_label[f'{part}/hex'], value.hex().encode())
            self.assertEqual(by_label[f'{part}/HEX'], value.hex().upper().encode())
            self.assertEqual(by_label[f'{part}/utf-16-le'], text.encode('utf-16-le'))
            self.assertEqual(by_label[f'{part}/utf-16-be'], text.encode('utf-16-be'))
            for shift in range(3):
                for name, encode in (('base64', base64.b64encode), ('base64url', base64.urlsafe_b64encode)):
                    needle = by_label[f'{part}/{name}@{shift}']
                    # inside any encoded stream that puts the value at that alignment
                    self.assertIn(needle, encode(b'p' * ((3 - shift) % 3) + value + b'tail'))
                    self.assertEqual(len(needle) % 4, 0)
        fragments = [n for n, labels in table.items() if 'fragment' in labels]
        self.assertEqual(sorted(fragments), sorted({body[i:i + 16].encode() for i in (0, 8, 16, 24)}))
        # nothing is a needle that the public prefix alone could produce
        prefix = KS.SYNTHETIC_PREFIX * 3
        for blob in (prefix.encode(), prefix.encode().hex().encode(), base64.b64encode(prefix.encode()),
                     prefix.encode('utf-16-le')):
            self.assertFalse(any(needle in blob for needle in table))

    def test_a_raw_run_of_23_body_characters_is_found_anywhere_and_22_need_not_be(self):
        for length in (16, 17, 23, 24, 40, 128):
            key = synthetic(length)
            body = key[len(KS.SYNTHETIC_PREFIX):]
            search = KS.Search(key, chunk=SMALL)
            for start in range(0, max(len(body) - 22, 0) + 1):
                run = body[start:start + 23]
                with self.subTest(length=length, start=start):
                    self.assertTrue(search.holds(b'x' + run.encode() + b'y'))
        body = synthetic(40)[len(KS.SYNTHETIC_PREFIX):]
        self.assertFalse(KS.Search(KS.SYNTHETIC_PREFIX + body).holds(body[1:16]))

    def test_the_shape_and_fingerprint_are_the_launchers_and_the_receipts(self):
        self.assertEqual(KS.SYNTHETIC_SHAPE.pattern, IQ.SYNTHETIC_SHAPE.pattern)
        self.assertEqual(KS.SYNTHETIC_PREFIX, IQ.SYNTHETIC_PREFIX)
        key = synthetic()
        self.assertEqual(KS.fingerprint(key), IQ.contract.fingerprint(key))
        self.assertEqual(KS.body_of('not-a-synthetic-key-at-all'), 'not-a-synthetic-key-at-all')
        search = KS.Search(key)
        self.assertNotIn(key[len(KS.SYNTHETIC_PREFIX):][:8], repr(search))
        self.assertIn(search.fingerprint, repr(search))
        for bad in ('short', 'x' * 1025, 'two words here!!', 'tab\there-and-more', 42):
            with self.assertRaises(KS.SearchError) as caught:
                KS.Search(bad)
            self.assertEqual(caught.exception.code, 'KEY_INVALID')

    def test_the_programmatic_checks_refuse_as_the_command_line_does(self):
        key = synthetic()
        self.assertEqual(KS.check_fingerprint(key, KS.fingerprint(key)), KS.fingerprint(key))
        for expected, code in (('sha256:XYZ', 'FINGERPRINT_INVALID'), (None, 'FINGERPRINT_INVALID'),
                               ('sha256:' + '0' * 16, 'FINGERPRINT_MISMATCH')):
            with self.assertRaises(KS.SearchError) as caught:
                KS.check_fingerprint(key, expected)
            self.assertEqual(caught.exception.code, code)
            self.assertTrue(str(caught.exception).startswith(f'{code}: '))
            self.assertIn('Remedy: ', str(caught.exception))
        for surfaces in ([], [('a', 'environ', 'self'), ('a', 'environ', 'self')]):
            with self.assertRaises(KS.SearchError) as caught:
                KS.run(key, KS.fingerprint(key), surfaces)
            self.assertEqual(caught.exception.code, 'SURFACE_INVALID')
        self.assertEqual(KS.body_of(KS.SYNTHETIC_PREFIX), KS.SYNTHETIC_PREFIX)
        for edge in ('!' * 16, '~' * 1024):
            self.assertEqual(KS.Search(edge).fingerprint, KS.fingerprint(edge))
        with self.assertRaises(ValueError):
            KS.Search(key).capture('x', b'', expect='maybe')
        search = KS.Search(key, chunk=SMALL)
        search.capture('clean', b'nothing')
        self.assertEqual(search.report()['verdict'], 'invalid')       # the controls were not run
        self.assertEqual(search.report()['controls']['failed'], ['not run'])
        search.controls()
        self.assertEqual(search.report()['verdict'], 'not-found')
        search.capture('two', key.encode() + b' ' + key.encode())
        search.capture('one', key.encode('utf-16-le'))
        self.assertTrue(search.report()['statement'].startswith('the key was found on 2 surface(s)'))
        self.assertEqual(KS.Search(key)._shown('n' * 300), 'n' * 200)

    def test_the_module_is_independent_of_the_broker(self):
        names = {n.module if isinstance(n, ast.ImportFrom) else a.name
                 for n in ast.walk(ast.parse(SOURCE)) if isinstance(n, (ast.Import, ast.ImportFrom))
                 for a in getattr(n, 'names', [])}
        self.assertFalse({n for n in names if n and ('inference' in n or 'contract' in n or 'credential' in n)})
        self.assertNotIn('_load', SOURCE)


class TestStream(unittest.TestCase):
    def test_a_match_across_a_read_boundary_is_counted_once(self):
        key = synthetic(40)
        search = KS.Search(key, chunk=SMALL)
        for offset in range(SMALL - len(key) - 2, SMALL + 2):
            data = b'\x00' * offset + key.encode() + b'\x00' * 50
            with self.subTest(offset=offset):
                report = search.capture('blob', data)
                self.assertEqual(report['matches'].get('key/raw'), 1, report)
                self.assertEqual(report['matches'].get('body/raw'), 1)
        twice = b'\x00' * (SMALL - 5) + key.encode() * 2
        self.assertEqual(search.capture('twice', twice)['matches']['key/raw'], 2)

    def test_without_the_overlap_a_straddling_copy_is_missed(self):
        key = synthetic(40)
        search = KS.Search(key, chunk=SMALL)
        data = b'\x00' * (SMALL - 20) + key.encode()
        real = KS._Stream.__init__

        def no_overlap(stream, table, longest):
            real(stream, table, longest)
            stream.keep = 0
        with mock.patch.object(KS._Stream, '__init__', no_overlap):
            missed = search.capture('blob', data)
            control = KS.Search(key, chunk=SMALL).controls()
        self.assertNotIn('key/raw', missed['matches'])
        self.assertFalse(control['valid'])
        self.assertTrue(any(c.startswith('chunk-boundary/') for c in control['failed']))


class TestControls(unittest.TestCase):
    def test_every_planted_copy_is_found_for_every_key_length(self):
        for length in (16, 17, 23, 40, 128):
            for _ in range(2):
                search = KS.Search(synthetic(length), chunk=SMALL)
                control = search.controls()
                with self.subTest(length=length):
                    self.assertTrue(control['valid'], control['failed'])
        self.assertEqual(set(control['kinds']), {
            'capture', 'chunk-boundary', 'gzip', 'file', 'sqlite', 'sqlite-overflow', 'http-chunked', 'http-gzip',
            'environ', 'tree', 'tar', 'tar-gz', 'tar-name'})
        self.assertEqual(set(control['carriers']), {
            'raw', 'json', 'url-form', 'url-quote', 'hex', 'HEX', 'utf-16-le', 'utf-16-be', 'body', 'fragment',
            'base64@0', 'base64@1', 'base64@2', 'base64url@0', 'base64url@1', 'base64url@2'})
        self.assertEqual(control['cases'], 16 * 8 + 14 + 16 * 3 + 1)
        self.assertEqual(KS.Search(synthetic()).chunk, KS.CHUNK)
        # the default chunk: the straddles cross a 1 MiB read
        self.assertTrue(KS.Search(synthetic()).controls()['valid'])

    def test_a_broken_view_invalidates_the_verdict(self):
        key = synthetic(40)
        real = KS._Gunzip
        for target, broken, kinds in (
                ('_sqlite_values', lambda data: iter(()), {'sqlite', 'sqlite-overflow'}),
                ('_http_messages', lambda data: iter(()), {'http-chunked', 'http-gzip'}),
                ('_decode_body', lambda body, coding, limit: None, {'http-gzip'}),
                ('_Gunzip', lambda *a: real(KS._Stream({b'\x01' * 9: ('x',)}, 9), *a[1:]), {'gzip'})):
            with self.subTest(target=target), mock.patch.object(KS, target, broken):
                search = KS.Search(key, chunk=SMALL)
                control = search.controls()
                self.assertFalse(control['valid'])
                self.assertEqual({c.split('/')[0] for c in control['failed']}, kinds)
                search.capture('clean', b'nothing')
                self.assertEqual(search.report()['verdict'], 'invalid')
        with mock.patch.object(KS.Search, 'holds', lambda self, data: False):
            control = KS.Search(key, chunk=SMALL).controls()
        self.assertEqual(control['failed'], ['tar-name/raw'])      # a name holding the key was shown

    def test_the_split_controls_hold_no_whole_copy_in_the_raw_view(self):
        search = KS.Search(synthetic(40), chunk=SMALL)
        for name, data in search.carriers():
            split = search._split_point(data)
            for image in (KS._sqlite_image(data, split=split), KS._chunked_response(data, split)):
                with self.subTest(name=name):
                    self.assertFalse(any(n in image for n, labels in search._table.items()
                                         if labels != ('fragment',)))
            self.assertTrue(search.holds(KS._sqlite_image(data)))


class TestViews(unittest.TestCase):
    def setUp(self):
        self.key = synthetic(40)
        self.search = KS.Search(self.key, chunk=SMALL)
        self.k = self.key.encode()

    def test_gzip_every_member_bounded_and_a_truncated_stream_incomplete(self):
        data = gzip.compress(b'a' * 10, mtime=0) + gzip.compress(b'\x00' * 9000 + self.k, mtime=0)
        report = self.search.capture('two members', data)
        self.assertEqual(report['matches_by_view']['gzip']['key/raw'], 1)
        self.assertNotIn('raw', report['matches_by_view'])
        self.assertTrue(report['complete'])
        self.assertEqual(report['bytes']['gzip'], 9010 + len(self.k))
        cut = self.search.capture('cut', data[:-30])
        self.assertIn('gzip: the stream ends inside a member', cut['incomplete'])
        self.assertFalse(cut['complete'])
        bad = self.search.capture('bad', KS.GZIP_MAGIC + b'\x00' * 40)
        self.assertIn('gzip: zlib.error', bad['incomplete'])
        with mock.patch.object(KS, 'GZIP_LIMIT', 5000):
            bomb = self.search.capture('bomb', gzip.compress(b'\x00' * 20000, mtime=0))
        self.assertIn('gzip: more than 5000 bytes decompressed', bomb['incomplete'])
        later = self.search.capture('later', b'x' * SMALL + gzip.compress(b'x', mtime=0)[:5])
        self.assertEqual((later['complete'], later['bytes'].get('gzip')), (True, None))
        trailing = self.search.capture('trailing', gzip.compress(self.k, mtime=0) + b'not gzip')
        self.assertTrue(trailing['complete'])
        self.assertEqual(trailing['matches_by_view']['gzip']['key/raw'], 1)

    def test_sqlite_rows_schema_wal_images_and_limits(self):
        connection = sqlite3.connect(':memory:')
        connection.execute('PRAGMA page_size = 4096')
        connection.execute('CREATE TABLE t (a TEXT, b BLOB, c INTEGER)')
        connection.execute('CREATE VIRTUAL TABLE v USING fts5(x)')
        connection.execute('INSERT INTO t VALUES (?, ?, 7)', ('x', zlib.compress(b'z')))
        connection.execute('INSERT INTO v VALUES (?)', (self.key,))
        connection.commit()
        image = bytearray(connection.serialize())
        connection.close()
        report = self.search.capture('db', bytes(image))
        self.assertGreater(report['bytes']['sqlite'], 0)
        self.assertIn('key/raw', report['matches_by_view']['sqlite'])
        self.assertTrue(report['complete'])
        image[18:20] = b'\x02\x02'                    # a write-ahead-log database's header
        self.assertIn('key/raw', self.search.capture('wal', bytes(image))['matches_by_view']['sqlite'])
        broken = self.search.capture('broken', KS.SQLITE_MAGIC + b'\x00' * 200)
        self.assertFalse(broken['complete'])
        self.assertTrue(any(k.startswith('sqlite: ') for k in broken['incomplete']))
        with mock.patch.object(KS, 'SQLITE_LIMIT', 100):
            big = self.search.capture('big', bytes(image))
        self.assertIn('sqlite: more than 100 bytes', big['incomplete'])
        self.assertIn('key/raw', big['matches_by_view']['raw'])

    def test_http_messages_requests_codings_and_parse_errors(self):
        body = json.dumps({'error': self.key}).encode()
        deflated = zlib.compress(body)
        raw_deflate = zlib.compressobj(wbits=-15)
        raw_deflate = raw_deflate.compress(body) + raw_deflate.flush()
        capture = (b'POST /v1/x HTTP/1.1\r\nHost: a\r\nContent-Length: 2\r\n\r\n{}'
                   b'GET /v1/y HTTP/1.1\r\nHost: a\r\n\r\n'
                   b'HTTP/1.1 204 No Content\r\n\r\n'
                   + b'HTTP/1.1 200 OK\r\nContent-Encoding: deflate\r\nContent-Length: %d\r\n\r\n' % len(deflated)
                   + deflated
                   + b'HTTP/1.1 200 OK\r\nContent-Encoding: deflate\r\nContent-Length: %d\r\n\r\n' % len(raw_deflate)
                   + raw_deflate
                   + b'HTTP/1.1 500 x\r\nTransfer-Encoding: chunked\r\n\r\n3;ext=1\r\nabc\r\n0\r\nX-T: 1\r\n\r\n'
                   + b'HTTP/1.1 200 OK\r\nConnection: close\r\n\r\nuntil the end')
        report = self.search.http('mixed', capture)
        self.assertTrue(report['complete'], report)
        self.assertEqual(report['items'], 7)
        self.assertEqual(report['matches_by_view']['http-decoded']['key/raw'], 2)
        self.assertEqual(report['where'], ['mixed message 4', 'mixed message 5'])
        chunked = b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n'
        for broken, fault in ((b'HTTP/1.1 200 OK\r\nContent-Length: 5\r\n', 'a message without the end of its headers'),
                              (b'HTTP/1.1 200 OK\r\nContent-Length: 50\r\n\r\nshort',
                               'a body shorter than its Content-Length'),
                              (b'HTTP/1.1 200 OK\r\nbad header\r\n\r\n', 'a header line without a colon'),
                              (b'NOT HTTP\r\n\r\n', 'not an HTTP/1.x start line'),
                              (chunked + b'zz\r\n', 'invalid literal for int() with base 16'),
                              (chunked + b'2', 'a chunk without its size line'),
                              (chunked + b'5\r\nab', 'a chunk shorter than its size'),
                              (chunked + b'2\r\nab\r\n0\r\n', 'a chunked body without its end'),
                              (chunked + b'2\r\nab', 'a chunk shorter than its size'),
                              (chunked + b'2\r\nabXY', 'a chunk shorter than its size'),
                              (b'HTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\nContent-Length: 3\r\n\r\nabc',
                               'the body does not decode')):
            with self.subTest(broken=broken[:40]):
                result = self.search.http('broken', broken)
                self.assertFalse(result['complete'])
                (got,) = result['incomplete']
                self.assertTrue(got.startswith('http: ' + fault), got)
        with mock.patch.object(KS, 'GZIP_LIMIT', 10):
            over = self.search.http('over', KS._gzip_response(b'x' * 100))
        self.assertIn('http: the decoded body is over the bound', over['incomplete'])

    def test_names_and_targets_are_searched_and_never_shown_with_a_match(self):
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode='w:gz') as tar:
            for name, kind, link in (('etc/plain', tarfile.REGTYPE, ''), (f'home/{self.key}.txt', tarfile.REGTYPE, ''),
                                     ('etc/link', tarfile.SYMTYPE, f'/x/{base64.b64encode(self.k).decode()}'),
                                     ('dev/fifo', tarfile.FIFOTYPE, ''), ('etc', tarfile.DIRTYPE, ''),
                                     ('home', tarfile.DIRTYPE, '')):
                info = tarfile.TarInfo(name)
                info.type, info.linkname = kind, link
                tar.addfile(info, io.BytesIO(b'') if kind == tarfile.REGTYPE else None)
        report = self.search.tar('collection', archive.getvalue())
        self.assertEqual(report['items'], 6)
        self.assertEqual(report['where'], [KS.WITHHELD, 'etc/link'])
        self.assertEqual(report['not_followed'], {'links': 1, 'special files': 1})
        self.assertIn('key/base64@0', report['matches_by_view']['name'])
        self.assertNotIn(self.key, json.dumps(report))
        corrupt = self.search.tar('corrupt', archive.getvalue()[:60])
        self.assertFalse(corrupt['complete'])
        self.assertEqual(self.search.tar('none', b'')['unreadable'], {'ReadError': 1})

    def test_environ_and_this_processes_environment(self):
        report = self.search.environ('mapping', {'A': 'x', 'B_KEY': self.key})
        self.assertEqual((report['items'], report['where']), (2, ['B_KEY']))
        own = self.search.environ('self')
        self.assertEqual(own['found'], 0)
        self.assertEqual(own['items'], len(os.environ))


class TestDisk(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-key-search-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.key = synthetic(40)
        self.k = self.key.encode()
        self.search = KS.Search(self.key, chunk=SMALL)

    def test_a_tree_every_file_links_not_followed_unreadable_counted(self):
        root = self.tmp / 'root'
        (root / 'logs' / 'deep').mkdir(parents=True)
        (root / 'logs' / 'a.jsonl').write_bytes(b'{"fingerprint": "%s"}\n' % KS.fingerprint(self.key).encode())
        (root / 'logs' / 'deep' / 'b.log.gz').write_bytes(gzip.compress(b'nothing'))
        outside = self.tmp / 'outside'
        outside.mkdir()
        (outside / 'held.txt').write_bytes(self.key.encode())
        linked = False
        try:
            import _winapi
            _winapi.CreateJunction(str(outside), str(root / 'junction'))
            linked = True
        except (ImportError, OSError):
            try:
                os.symlink(outside, root / 'junction', target_is_directory=True)
                linked = True
            except OSError:
                pass
        clean = self.search.tree('instance', root)
        self.assertEqual((clean['found'], clean['complete']), (0, True), clean)
        self.assertEqual(clean['items'], 2 + linked)
        self.assertEqual(clean['not_followed'], {'links': 1} if linked else {})
        self.assertGreater(clean['bytes']['gzip'], 0)
        self.assertGreater(clean['bytes']['name'], 0)
        (root / 'logs' / 'deep' / 'planted.hex').write_bytes(binascii.hexlify(self.k))
        found = self.search.tree('instance', root)
        self.assertEqual(found['where'], ['logs/deep/planted.hex'])
        self.assertEqual(found['matches'], {'key/hex': 1, 'body/hex': 1})
        with mock.patch.object(builtins, 'open', side_effect=PermissionError('locked')):
            locked = self.search.tree('locked', root)
        self.assertEqual(locked['unreadable'], {'PermissionError': 3})
        self.assertFalse(locked['complete'])
        self.assertEqual(self.search.tree('missing', self.tmp / 'nothing')['unreadable'], {'not a directory': 1})
        self.assertEqual(self.search.file('missing', self.tmp / 'nothing')['unreadable'],
                         {'FileNotFoundError': 1})
        named = self.tmp / 'named'
        named.mkdir()
        (named / f'{self.key[-30:]}.txt').write_bytes(b'nothing')
        report = self.search.tree('named', named)
        self.assertEqual((report['where'], list(report['matches_by_view'])), ([KS.WITHHELD], ['name']))
        with mock.patch.object(KS.os, 'lstat', side_effect=PermissionError('denied')):
            denied = self.search.file('denied', root / 'logs' / 'a.jsonl')
        self.assertEqual(denied['unreadable'], {}, denied)          # lstat refused: read anyway, and it reads
        self.assertGreater(denied['bytes']['raw'], 0)
        if linked:
            target = self.tmp / self.key[-30:]
            target.mkdir()
            try:
                import _winapi
                _winapi.CreateJunction(str(target), str(named / 'link'))
            except (ImportError, OSError):
                os.symlink(target, named / 'link', target_is_directory=True)
            report = self.search.tree('named', named)
            self.assertIn(KS.WITHHELD, report['where'])
            self.assertEqual(report['not_followed'], {'links': 1})
            self.assertGreaterEqual(report['matches_by_view']['name']['fragment'], 2)
            self.assertEqual(self.search.tree('junction', root / 'junction')['unreadable'], {'not a directory': 1})
            self.assertEqual(self.search.file('junction', root / 'junction')['not_followed'], {'links': 1})

    def test_the_command_line_reads_the_key_from_a_pipe_and_writes_and_prints_no_copy(self):
        root = self.tmp / 'reports'
        root.mkdir()
        (root / 'report.json').write_text('{"provider_key": "%s"}\n' % KS.fingerprint(self.key), encoding='utf-8')
        archive = self.tmp / 'collection.tar.gz'
        archive.write_bytes(KS._tar_image([('etc/hosts', b'127.0.0.1 localhost\n')], 'gz'))
        fp = KS.fingerprint(self.key)
        argv = ['search', '--expect-fingerprint', fp, '--surface', f'reports=tree:{root}',
                '--surface', f'one=file:{root / "report.json"}', '--surface', f'guest=tar:{archive}',
                '--surface', 'env=environ:self']
        before = sorted(p.relative_to(self.tmp) for p in self.tmp.rglob('*'))
        opened = []
        real_open = builtins.open

        def watching(file, mode='r', *args, **kwargs):
            opened.append(mode)
            return real_open(file, mode, *args, **kwargs)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(builtins, 'open', watching), mock.patch('sys.stdout', new_callable=io.StringIO) as so, \
                mock.patch('sys.stderr', new_callable=io.StringIO) as se:
            code = KS.main(argv, Pipe((self.key + '\r\n').encode()), out, err)
        self.assertEqual(code, 0, err.getvalue())
        self.assertEqual((so.getvalue(), se.getvalue()), ('', ''))
        self.assertEqual(set(opened), {'rb'})
        self.assertEqual(sorted(p.relative_to(self.tmp) for p in self.tmp.rglob('*')), before)
        report = json.loads(out.getvalue())
        self.assertEqual(report['verdict'], 'not-found')
        self.assertEqual([s['label'] for s in report['surfaces']], ['reports', 'one', 'guest', 'env'])
        self.assertTrue(all(s['searched'] and s['complete'] and s['bytes_total'] > 0 for s in report['surfaces']))
        self.assertIn('it is not proof that the key is absent anywhere else', report['statement'])
        self.assertIn('process memory', report['not_covered'][0])
        self.assertTrue(report['controls']['valid'])
        self.assertIn('inference-key-search: not-found: ', err.getvalue())
        self.assertIn('controls valid (191 cases)', err.getvalue())
        text = out.getvalue() + err.getvalue()
        self.assertFalse(KS.Search(self.key).holds(text))
        for part in substrings(self.key):
            self.assertNotIn(part, text)
        # a planted copy on any surface: found, exit 1 (from here on with a small read chunk, for time)
        (root / 'planted.b64').write_bytes(base64.b64encode(b'user:' + self.k))
        out = io.StringIO()
        self.enterContext(mock.patch.object(KS, 'CHUNK', SMALL))
        self.assertEqual(KS.main(argv, Pipe(self.key.encode()), out, io.StringIO()), 1)
        report = json.loads(out.getvalue())
        self.assertEqual(report['verdict'], 'found')
        self.assertEqual(report['surfaces'][0]['where'], ['planted.b64'])
        self.assertFalse(KS.Search(self.key).holds(out.getvalue()))
        # a surface that cannot be read: incomplete, exit 1
        out = io.StringIO()
        missing = ['search', '--expect-fingerprint', fp, '--surface', f'gone=tar:{self.tmp / "gone.tar"}']
        self.assertEqual(KS.main(missing, Pipe(self.key.encode()), out, io.StringIO()), 1)
        report = json.loads(out.getvalue())
        self.assertEqual(report['verdict'], 'incomplete')
        self.assertEqual((report['surfaces'][0]['searched'], report['surfaces'][0]['unreadable']),
                         (True, {'FileNotFoundError': 1}))

    def test_the_command_lines_refusals_never_repeat_the_key(self):
        fp = KS.fingerprint(self.key)
        surface = ['--surface', f'r=tree:{self.tmp}']
        other = synthetic(40)
        body = self.key[len(KS.SYNTHETIC_PREFIX):]
        for argv, data, tty, code in (
                (['--expect-fingerprint', fp] + surface, self.key.encode(), True, 'KEY_STDIN_TTY'),
                (['--expect-fingerprint', fp] + surface, b'sk-' + self.key.encode(), False, 'KEY_NOT_SYNTHETIC'),
                (['--expect-fingerprint', fp] + surface, self.key.encode() + b' x', False, 'KEY_INVALID'),
                (['--expect-fingerprint', fp] + surface, b'\xff' * 20, False, 'KEY_INVALID'),
                (['--expect-fingerprint', fp] + surface, b'', False, 'KEY_INVALID'),
                (['--expect-fingerprint', fp] + surface, other.encode(), False, 'FINGERPRINT_MISMATCH'),
                (['--expect-fingerprint', 'sha256:XYZ'] + surface, self.key.encode(), False, 'FINGERPRINT_INVALID'),
                (['--expect-fingerprint', fp, '--surface', 'r=disk:/x'], self.key.encode(), False, 'SURFACE_INVALID'),
                (['--expect-fingerprint', fp, '--surface', 'r=environ:/x'], self.key.encode(), False,
                 'SURFACE_INVALID'),
                (['--expect-fingerprint', fp, '--surface', 'bad label=tree:/x'], self.key.encode(), False,
                 'SURFACE_INVALID'),
                (['--expect-fingerprint', fp] + surface + surface, self.key.encode(), False, 'SURFACE_INVALID')):
            with self.subTest(code=code):
                stdin = Pipe(data, tty)
                out, err = io.StringIO(), io.StringIO()
                self.assertEqual(KS.main(['search'] + argv, stdin, out, err), 2, err.getvalue())
                self.assertIn(code, err.getvalue())
                self.assertEqual(out.getvalue(), '')
                self.assertFalse(KS.Search(self.key).holds(err.getvalue()))
                self.assertFalse(KS.Search(other).holds(err.getvalue()))
                if code in ('FINGERPRINT_INVALID', 'SURFACE_INVALID'):
                    self.assertEqual(stdin.tell(), 0, 'the key was read before the arguments were checked')
        # a report that would hold the key is withheld (here: the body given as a surface label)
        out, err = io.StringIO(), io.StringIO()
        self.enterContext(mock.patch.object(KS, 'CHUNK', SMALL))
        code = KS.main(['search', '--expect-fingerprint', fp, f'--surface={body}=tree:{self.tmp}'],
                       Pipe(self.key.encode()), out, err)
        self.assertEqual((code, out.getvalue()), (1, ''))
        self.assertIn('OUTPUT_WITHHELD', err.getvalue())
        self.assertFalse(KS.Search(self.key).holds(err.getvalue()))
        for argv in ([], ['search'], ['search', '--expect-fingerprint', fp], ['search', '--surface', 'a=environ:self']):
            with self.subTest(argv=argv), mock.patch('sys.stderr', new_callable=io.StringIO), \
                    self.assertRaises(SystemExit) as caught:
                KS.main(argv, Pipe(), io.StringIO(), io.StringIO())
            self.assertEqual(caught.exception.code, 2)
        self.assertEqual(KS.read_key(Pipe((self.key + '\n').encode())), self.key)
        self.assertEqual(KS.read_key(io.StringIO(self.key)), self.key)
        with self.assertRaises(KS.SearchError):
            KS.read_key(None)


class TestNothingKept(unittest.TestCase):
    """The module prints, logs and writes nothing: no print, no logging, no file opened for writing, no
    temporary file, no environment change."""

    def test_its_syntax_tree_writes_nothing(self):
        tree = ast.parse(SOURCE)
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
        names = {getattr(c.func, 'id', None) for c in calls} | {getattr(c.func, 'attr', None) for c in calls}
        self.assertFalse(names & {'print', 'write_text', 'write_bytes', 'mkdir', 'makedirs', 'mkstemp', 'mkdtemp',
                                  'NamedTemporaryFile', 'TemporaryDirectory', 'putenv', 'unsetenv', 'unlink',
                                  'copyfile', 'backup', 'basicConfig', 'symlink', 'chmod'})
        os_calls = {ast.unparse(c.func) for c in calls if re.fullmatch(r'os(\.\w+)+', ast.unparse(c.func))}
        self.assertLessEqual(os_calls, {'os.fspath', 'os.lstat', 'os.readlink', 'os.walk', 'os.path.basename',
                                        'os.path.isdir', 'os.path.islink', 'os.path.join', 'os.path.relpath'})
        for call in calls:
            if getattr(call.func, 'id', None) == 'open':
                modes = [a.value for a in call.args[1:2]] + [k.value.value for k in call.keywords if k.arg == 'mode']
                self.assertEqual(modes, ['rb'], ast.unparse(call))
            if getattr(call.func, 'id', None) == 'connect':
                self.fail('a connection is opened')
        sqlite_connects = [ast.unparse(c) for c in calls if getattr(c.func, 'attr', None) == 'connect']
        self.assertEqual(set(sqlite_connects), {"sqlite3.connect(':memory:')"})
        imported = {a.name.split('.')[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        self.assertFalse(imported & {'logging', 'tempfile', 'shutil', 'socket', 'http', 'subprocess'})
        writes = [ast.unparse(c.func) for c in calls if getattr(c.func, 'attr', None) == 'write']
        self.assertEqual(sorted(writes), ['err.write', 'err.write', 'out.write'])     # main's three, nothing else


if __name__ == '__main__':
    unittest.main()
