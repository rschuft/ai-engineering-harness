"""Tests for tools/guest.py image-inspect's text mode (S-03.3 D-1; stdlib unittest; no network,
no guest).

Run from the repository root:  python -I -B -m unittest discover -s tools/tests -v

Every docker-archive, and every PyInstaller executable inside one, is synthetic and built in
memory: no temporary directory, no file written, no process launched. The PYZ modules are
compiled from short source texts by this interpreter (marshal data of the same code-object
layout as CPython 3.13's) and are only walked as data by the code under test.
"""
from pathlib import Path
import contextlib
import importlib.util
import io
import json
import marshal
import struct
import sys
import unittest
import zlib
from unittest import mock

CATEGORY = 'unit'

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_image_inspect as base  # noqa: E402  (the synthetic archive builders)

guest = base.guest
F, D, S, H, layer, archive, digest = base.F, base.D, base.S, base.H, base.layer, base.archive, \
    base.digest
NL = chr(10)
PYVER = sys.version_info[0] * 100 + sys.version_info[1]


def text(**kw):
    return guest.parse_image_text_requests(**kw)


def run(layers, paths=(), **kw):
    data, image = archive(layers)
    out = guest.read_image_archive(io.BytesIO(data), image, base.specs(*paths), text(**kw))
    return out['text'], out


def pyz(modules, toc_hook=None):
    """A PYZ archive as PyInstaller writes it: header, zlib'd marshal code objects, then the
    marshal table of contents [(name, (type, offset, length))]."""
    blob = bytearray(b'PYZ' + bytes([0]) + importlib.util.MAGIC_NUMBER + bytes(4))
    toc = []
    for name, value in modules.items():
        data = value if isinstance(value, bytes) else \
            zlib.compress(marshal.dumps(compile(value, f'/build/{name}.py', 'exec')))
        toc.append((name, (1 if name.endswith('__init__') else 0, len(blob), len(data))))
        blob += data
    at = len(blob)
    blob += marshal.dumps(toc_hook(toc) if toc_hook else toc)
    blob[8:12] = struct.pack('!i', at)
    return bytes(blob)


def pyinstaller(modules, pyver=PYVER, decoy=True, toc_hook=None, kind=b'z'):
    """An executable: a bootloader (holding its own copy of the cookie magic, as a real one
    does), then the CArchive: entries, table of contents, cookie."""
    boot = bytes([127]) + b'ELF' + bytes(40) + (guest.PYI_COOKIE if decoy else b'') + bytes(24)
    pkg, toc = bytearray(), bytearray()
    for name, data, code in ((b'pyiboot01', b'print(1)', b's'),
                             (b'PYZ-00.pyz', pyz(modules, toc_hook), kind)):
        offset = len(pkg)
        pkg += data
        padded = name + bytes(16 - len(name) % 16)
        toc += struct.pack(guest.PYI_TOC_ENTRY, 18 + len(padded), offset, len(data), len(data), 0,
                           code) + padded
    toc_at = len(pkg)
    pkg += toc
    size = struct.calcsize(guest.PYI_COOKIE_FORMAT)
    cookie = struct.pack(guest.PYI_COOKIE_FORMAT, guest.PYI_COOKIE, len(pkg) + size, toc_at,
                         len(toc), pyver, b'libpython3.so')
    return boot + bytes(pkg) + cookie


MODELS = (
    'class SendMessageRequest:' + NL +
    '    """A message sent to a conversation."""' + NL +
    '    role = "user"' + NL +
    '    run = False' + NL +
    '    def to_body(self):' + NL +
    '        return {"content": self.content, "next_page_id": None}' + NL)
EXE = '/usr/local/bin/server'


class Globs(unittest.TestCase):
    def match(self, glob, path):
        return guest.image_glob_regex(glob).fullmatch(path) is not None

    def test_components_and_double_star(self):
        self.assertTrue(self.match('/a/**/b.js', 'a/b.js'))
        self.assertTrue(self.match('/a/**/b.js', 'a/x/y/b.js'))
        self.assertFalse(self.match('/a/*', 'a/x/y'))
        self.assertTrue(self.match('/a/**', 'a/x/y'))
        self.assertFalse(self.match('/a/**', 'a'))
        self.assertTrue(self.match('/**/package.json', 'p/q/package.json'))
        self.assertTrue(self.match('/x/[ab]?.js', 'x/b1.js'))
        self.assertFalse(self.match('/x/[!ab]*', 'x/a1'))
        self.assertTrue(self.match('/@scope/a.b', '@scope/a.b'))
        self.assertFalse(self.match('/@scope/a.b', '@scope/axb'))

    def test_bad_globs_are_refused(self):
        for bad in ('rel/x', '/a//b', '/a/../b', '/a/./b', '/a/[x', '/a/' + chr(0)):
            with self.assertRaises(guest.Refused, msg=bad):
                guest.image_glob_regex(bad)


class Requests(unittest.TestCase):
    def refused(self, **kw):
        with self.assertRaises(guest.Refused) as caught:
            text(**kw)
        return str(caught.exception)

    def test_patterns(self):
        self.assertIn('empty string', self.refused(searches=[('/a', 'x*')]))
        self.assertIn('one group', self.refused(distincts=[('/a', '(a)(b)')]))
        self.assertIn('not a regular expression', self.refused(searches=[('/a', '(')]))
        self.assertIn('1 to', self.refused(searches=[('/a', 'x' * 257)]))
        self.assertIn('1 to', self.refused(searches=[('/a', '')]))

    def test_bounds(self):
        self.assertIn('--context', self.refused(lists=['/a'], context=401))
        self.assertIn('--context', self.refused(lists=['/a'], context=-1))
        self.assertIn('--max-matches', self.refused(lists=['/a'], max_matches=0))
        self.assertIn('--max-matches', self.refused(lists=['/a'], max_matches=51))
        self.assertIn('at most', self.refused(lists=['/a'] * (guest.IMAGE_TEXT_MAX_REQUESTS + 1)))
        self.assertIn('lines', self.refused(excerpts=[('/a', 0, 3)]))
        self.assertIn('lines', self.refused(excerpts=[('/a', 5, 4)]))
        self.assertIn('lines', self.refused(excerpts=[('/a', 1, 201)]))
        self.assertIn('exact', self.refused(excerpts=[('/a/*', 1, 2)]))
        self.assertIn('takes a path', self.refused(excerpts=[('/a!b', 1, 2)]))

    def test_member_targets(self):
        self.assertIn('needs EXE!MODULE', self.refused(strings=['/usr/bin/x']))
        self.assertIn('exact absolute', self.refused(strings=['/usr/*/x!m']))
        self.assertIn('exact absolute', self.refused(lists=['x!m']))
        self.assertIn('after !', self.refused(searches=[('/x!', 'a')]))
        self.assertIn('after !', self.refused(searches=[('/x!a/b', 'a')]))
        got = text(lists=['/x!openhands.*'], strings=['/x!m'])['requests']
        self.assertEqual([(r['op'], r['exe'], r['modules']) for r in got],
                         [('list', '/x', 'openhands.*'), ('strings', '/x', 'm')])


class ListsAndExcerpts(unittest.TestCase):
    def test_list_reports_metadata_in_path_order(self):
        l0 = layer([D('p'), F('p/b.js', b'bb', mode=0o755), F('p/a.js', b'a'), D('p/sub'),
                    F('p/sub/c.js', b'c'), S('p/link.js', 'a.js')])
        out, _ = run([l0], lists=['/p/*', '/p/**/*.js', '/nothing/*'])
        first, deep, none = out['lists']
        self.assertEqual([e['path'] for e in first['entries']],
                         ['/p/a.js', '/p/b.js', '/p/link.js'])      # the directory is not listed
        self.assertEqual(first['entries'][1], {'path': '/p/b.js', 'type': 'file', 'mode': '0755',
                                               'uid': 0, 'gid': 0, 'size': 2, 'layer': 0})
        self.assertEqual(first['entries'][2], {'path': '/p/link.js', 'type': 'symlink',
                                               'link_target': 'a.js'})
        self.assertEqual((first['total'], first['truncated']), (3, False))
        self.assertEqual([e['path'] for e in deep['entries']],
                         ['/p/a.js', '/p/b.js', '/p/link.js', '/p/sub/c.js'])
        self.assertEqual((none['total'], none['entries']), (0, []))

    def test_list_cap_is_reported(self):
        l0 = layer([F(f'f{i}') for i in range(5)])
        with mock.patch.object(guest, 'IMAGE_TEXT_MAX_LIST', 3):
            out, _ = run([l0], lists=['/*'])
        self.assertEqual((out['lists'][0]['total'], len(out['lists'][0]['entries']),
                          out['lists'][0]['truncated']), (5, 3, True))

    def test_excerpt_lines(self):
        body = ('one' + NL + 'two' + chr(13) + NL + 'x' * 700 + NL + 'tab' + chr(9) + 'bell' +
                chr(7) + NL).encode()
        l0 = layer([F('t.txt', body), S('l.txt', 't.txt')])
        out, _ = run([l0], excerpts=[('/l.txt', 2, 9)])
        got = out['excerpts'][0]
        self.assertEqual((got['present'], got['real_path'], got['sha256'], got['lines_total']),
                         (True, '/t.txt', digest(body)[7:], 4))
        self.assertEqual([line['n'] for line in got['lines']], [2, 3, 4])
        self.assertEqual(got['lines'][0], {'n': 2, 'text': 'two'})
        self.assertEqual((len(got['lines'][1]['text']), got['lines'][1]['truncated'],
                          got['lines'][1]['chars']), (600, True, 700))
        self.assertEqual(got['lines'][2]['text'], 'tab' + chr(9) + 'bell' + chr(92) + 'x07')

    def test_excerpt_refusals(self):
        l0 = layer([F('bin', b'ab' + bytes([0]) + b'cd'), F('latin', bytes([0xe9, 0x41])),
                    D('dir'), F('big', b'z' * 50)])
        with mock.patch.object(guest, 'IMAGE_TEXT_MAX_EXCERPT_FILE', 10):
            out, _ = run([l0], excerpts=[('/bin', 1, 1), ('/latin', 1, 1), ('/dir', 1, 1),
                                         ('/none', 1, 1), ('/big', 1, 1)])
        got = {e['path']: e for e in out['excerpts']}
        self.assertEqual(got['/bin']['refused'], 'binary (a NUL byte)')
        self.assertEqual(got['/latin']['refused'], 'binary (not UTF-8)')
        self.assertEqual(got['/dir']['refused'], 'a dir, not a file')
        self.assertEqual(got['/none'], {'path': '/none', 'present': False, 'start': 1, 'end': 1})
        self.assertEqual(got['/big']['refused'], 'larger than the excerpt bound')
        for entry in out['excerpts']:
            self.assertNotIn('lines', entry)
        self.assertEqual(got['/bin']['sha256'], digest(b'ab' + bytes([0]) + b'cd')[7:])


class Searches(unittest.TestCase):
    def test_matches_lines_and_context(self):
        js = ('const a = 1;' + NL + 'env.ANTHROPIC_BASE_URL || x;' + NL +
              'y(ANTHROPIC_BASE_URL)' + NL).encode()
        elf = bytes([127]) + b'ELF' + bytes([0, 1, 2]) + b'ANTHROPIC_BASE_URL' + bytes([0, 200])
        l0 = layer([D('pkg'), F('pkg/a.js', js), F('pkg/cli', elf), F('pkg/none.js', b'nothing'),
                    S('pkg/link', 'a.js')])
        out, _ = run([l0], searches=[('/pkg/*', 'ANTHROPIC_BASE_URL')], context=6)
        got = out['searches'][0]
        self.assertEqual((got['files_total'], got['files_with_matches'], got['matches_total'],
                          got['matches_reported'], got['skipped_total']), (3, 2, 3, 3, 1))
        self.assertEqual(got['skipped'], [{'path': '/pkg/link', 'type': 'symlink',
                                           'link_target': 'a.js'}])
        files = {f['path']: f for f in got['files']}
        a = files['/pkg/a.js']
        self.assertEqual((a['binary'], a['matches_total'], a['sha256']),
                         (False, 2, digest(js)[7:]))
        self.assertEqual(a['matches'][0], {'offset': 17, 'line': 2, 'match': 'ANTHROPIC_BASE_URL',
                                           'before': ';' + NL + 'env.', 'after': ' || x;'})
        self.assertEqual(a['matches'][1]['line'], 3)
        cli = files['/pkg/cli']['matches'][0]
        self.assertTrue(files['/pkg/cli']['binary'])
        self.assertNotIn('line', cli)
        self.assertEqual(cli['before'], 'ELF' + chr(92) + 'x00' + chr(92) + 'x01' + chr(92) +
                         'x02')
        self.assertEqual(cli['after'], chr(92) + 'x00' + chr(92) + 'xc8')
        self.assertEqual(files['/pkg/none.js']['matches'], [])

    def test_match_caps(self):
        data = b'k=1 ' * 30
        l0 = layer([F('a', data), F('b', data)])
        with mock.patch.object(guest, 'IMAGE_TEXT_MAX_REQUEST_MATCHES', 5), \
                mock.patch.object(guest, 'IMAGE_TEXT_MAX_COUNT', 20):
            out, _ = run([l0], searches=[('/*', 'k=')], max_matches=4)
        a, b = out['searches'][0]['files']
        self.assertEqual((len(a['matches']), a['matches_total'], a['count_capped']), (4, 20, True))
        self.assertEqual((len(b['matches']), b['matches_omitted']), (1, 3))
        self.assertEqual(out['searches'][0]['matches_reported'], 5)
        self.assertEqual(out['bounds']['max_matches_per_file'], 4)

    def test_long_match_is_cut(self):
        out, _ = run([layer([F('a', b'<' + b'x' * 300 + b'>')])], searches=[('/a', '<x+>')])
        match = out['searches'][0]['files'][0]['matches'][0]
        self.assertEqual((len(match['match']), match['match_truncated']), (200, True))

    def test_file_caps(self):
        l0 = layer([F(f'f{i}', b'hit') for i in range(4)] + [F('big', b'hit' * 10)])
        with mock.patch.object(guest, 'IMAGE_TEXT_MAX_FILES', 3):
            out, _ = run([l0], searches=[('/f*', 'hit')])
        got = out['searches'][0]
        self.assertEqual((got['files_total'], len(got['files']), got['files_truncated']),
                         (4, 3, True))
        with mock.patch.object(guest, 'IMAGE_TEXT_MAX_FILE', 10):
            out, _ = run([l0], searches=[('/big', 'hit')], excerpts=[('/big', 1, 1)])
        big = out['searches'][0]['files'][0]
        self.assertEqual((big['refused'], big['sha256']),
                         ('larger than the text bound', digest(b'hit' * 10)[7:]))
        self.assertNotIn('matches', big)
        self.assertEqual(out['excerpts'][0]['refused'], 'larger than the text bound')

    def test_hard_link_and_later_layers(self):
        l0 = layer([F('f', b'old needle'), H('h', 'f')], gz=False)
        l1 = layer([F('f', b'new')])
        out, _ = run([l0, l1], searches=[('/*', 'needle')])
        files = {f['path']: f for f in out['searches'][0]['files']}
        self.assertEqual(files['/h']['matches_total'], 1)
        self.assertEqual(files['/h']['hardlink_to'], '/f')
        self.assertEqual((files['/f']['matches_total'], files['/f']['layer']), (0, 1))

    def test_distinct_values(self):
        l0 = layer([F('a', b'X_ONE X_TWO X_ONE env.X_TWO'), F('b', b'X_ONE'), F('c', b'none')])
        out, _ = run([l0], distincts=[('/*', 'X_[A-Z]+'), ('/*', r'env\.(X_[A-Z]+)')])
        whole, group = out['distinct']
        self.assertEqual(whole['values'], [{'value': 'X_ONE', 'count': 3, 'files': 2},
                                           {'value': 'X_TWO', 'count': 2, 'files': 1}])
        self.assertEqual((whole['distinct_total'], whole['matches_total'],
                          whole['distinct_truncated']), (2, 5, False))
        self.assertEqual(group['values'], [{'value': 'X_TWO', 'count': 1, 'files': 1}])
        for item in whole['files']:
            self.assertNotIn('_counts', item)
        with mock.patch.object(guest, 'IMAGE_TEXT_MAX_DISTINCT', 1), \
                mock.patch.object(guest, 'IMAGE_TEXT_MAX_DISTINCT_HELD', 1):
            out, _ = run([l0], distincts=[('/a', 'X_[A-Z]+')])
        got = out['distinct'][0]
        self.assertEqual((got['distinct_truncated'], got['files'][0]['distinct_held_capped']),
                         (False, True))
        self.assertEqual(got['values'], [{'value': 'X_ONE', 'count': 2, 'files': 1}])

    def test_the_lock_still_binds_text_requests(self):
        data, image = archive([layer([F('a', b'hit')])])
        image['layers'][0]['digest'] = 'sha256:' + 'c' * 64
        with self.assertRaises(guest.Refused) as caught:
            guest.read_image_archive(io.BytesIO(data), image, [], text(searches=[('/a', 'hit')]))
        self.assertEqual(caught.exception.code, 'IMAGE_MISMATCH')

    def test_without_text_the_output_is_unchanged(self):
        data, image = archive([layer([F('a', b'x')])])
        out = guest.read_image_archive(io.BytesIO(data), image, base.specs('/a'))
        self.assertEqual(sorted(out), ['anomalies', 'config', 'nodes', 'paths'])
        _, with_text = run([layer([F('a', b'x')])], ['/a'], lists=['/a'])
        self.assertEqual(with_text['paths'], out['paths'])


class PyInstaller(unittest.TestCase):
    def exe_layer(self, exe):
        return layer([D('usr'), D('usr/local'), D('usr/local/bin'),
                      F('usr/local/bin/server', exe, mode=0o755),
                      S('usr/local/bin/alias', 'server')])

    def modules(self):
        return {'openhands.agent_server.models': MODELS,
                'openhands.sdk.event.__init__': 'KIND = "ACPToolCallEvent"',
                'requests.api': 'URL = "https://example.invalid/next_page_id"'}

    def test_list_search_and_strings(self):
        exe = pyinstaller(self.modules())
        out, _ = run([self.exe_layer(exe)], lists=['/usr/local/bin/alias!openhands.*'],
                     searches=[(EXE + '!openhands.*', 'next_page_id')],
                     distincts=[(EXE + '!*', 'ACP[A-Za-z]+Event')],
                     strings=[EXE + '!openhands.agent_server.models'])
        listed = out['lists'][0]
        self.assertEqual((listed['exe']['real_path'], listed['exe']['sha256'],
                          listed['modules_total']), ('/usr/local/bin/server', digest(exe)[7:], 2))
        self.assertEqual([(f['path'], f['kind']) for f in listed['files']],
                         [('/usr/local/bin/alias!openhands.agent_server.models', 'module'),
                          ('/usr/local/bin/alias!openhands.sdk.event.__init__', 'package')])
        info = listed['pyinstaller']
        self.assertEqual((info['python'], info['pyz_entry'], info['modules'], info['pyz_magic']),
                         (PYVER, 'PYZ-00.pyz', 3, importlib.util.MAGIC_NUMBER.hex()))
        search = out['searches'][0]
        self.assertEqual(search['files_with_matches'], 1)          # requests.api is not searched
        hit = search['files'][0]
        self.assertEqual((hit['path'], hit['binary']),
                         (EXE + '!openhands.agent_server.models', True))
        self.assertEqual(hit['matches'][0]['match'], 'next_page_id')
        self.assertNotIn('line', hit['matches'][0])
        self.assertEqual(out['distinct'][0]['values'],
                         [{'value': 'ACPToolCallEvent', 'count': 1, 'files': 1}])
        mod = out['strings'][0]['files'][0]
        self.assertEqual(mod['filename'], '/build/openhands.agent_server.models.py')
        codes = {c['code']: c for c in mod['codes']}
        self.assertEqual(list(codes), ['<module>', 'SendMessageRequest',
                                       'SendMessageRequest.to_body'])
        cls = codes['SendMessageRequest']
        self.assertEqual(cls['line'], 1)
        self.assertIn('A message sent to a conversation.', cls['consts'])
        self.assertIn('user', cls['consts'])
        self.assertTrue({'role', 'run'} <= set(cls['names']))
        method = codes['SendMessageRequest.to_body']
        self.assertEqual(method['line'], 5)
        self.assertTrue({'content', 'next_page_id'} <= set(method['consts']))
        self.assertFalse(mod['strings_truncated'])

    def test_strings_cap_and_module_cap(self):
        exe = pyinstaller({f'm{i}': 'A = ' + repr([f's{j}' for j in range(30)]) for i in range(3)})
        with mock.patch.object(guest, 'IMAGE_TEXT_MAX_STRINGS', 10), \
                mock.patch.object(guest, 'IMAGE_TEXT_MAX_STRINGS_MODULES', 2):
            out, _ = run([self.exe_layer(exe)], strings=[EXE + '!m*'])
        got = out['strings'][0]
        self.assertEqual((got['modules_total'], len(got['files']), got['modules_truncated']),
                         (3, 2, True))
        strings = sum(len(c['consts']) + len(c['names']) for c in got['files'][0]['codes'])
        self.assertEqual((strings, got['files'][0]['strings_truncated']), (10, True))

    def test_the_bootloader_copy_of_the_magic_is_skipped(self):
        exe = pyinstaller({'m': 'X = 1'}, decoy=True)
        archive_ = guest.pyi_archive(exe)
        self.assertEqual(archive_['cookie_offset'], len(exe) -
                         struct.calcsize(guest.PYI_COOKIE_FORMAT))
        self.assertEqual(list(archive_['modules']), ['m'])
        listed = pyinstaller({'m': 'X = 1'}, toc_hook=lambda toc: [[n, list(e)] for n, e in toc])
        self.assertEqual(guest.pyi_archive(listed)['modules']['m'][0], 0)
        as_dict = pyinstaller({'m': 'X = 1'}, toc_hook=dict)
        self.assertEqual(list(guest.pyi_archive(as_dict)['modules']), ['m'])

    def test_refusals(self):
        bomb = zlib.compress(bytes(4096))
        cases = {
            'plain': b'not an executable at all',
            'nopyz': pyinstaller({'m': 'X = 1'}, kind=b'x'),
            'float': pyinstaller({'m': 'X = 1'}, toc_hook=lambda toc: [(n, (t, o, ln), 1.5)
                                                                      for n, (t, o, ln) in toc]),
            'shape': pyinstaller({'m': 'X = 1'}, toc_hook=lambda toc: [n for n, _ in toc]),
        }
        for name, exe in cases.items():
            with self.assertRaises(guest._PyiError, msg=name):
                guest.pyi_archive(exe)
        exe = pyinstaller({'bomb': bomb, 'junk': b'not zlib'})
        with mock.patch.object(guest, 'IMAGE_TEXT_MAX_MODULE', 1024):
            out, _ = run([self.exe_layer(exe)], searches=[(EXE + '!*', 'x')])
        got = {f['path'].rpartition('!')[2]: f for f in out['searches'][0]['files']}
        self.assertEqual(got['bomb']['refused'], 'larger than the module bound')
        self.assertTrue(got['junk']['refused'].startswith('not zlib data'))
        out, _ = run([self.exe_layer(b'plain bytes')], lists=[EXE + '!*'])
        self.assertTrue(out['lists'][0]['refused'].startswith('not a readable PyInstaller'))
        self.assertEqual(out['lists'][0]['files'], [])
        out, _ = run([self.exe_layer(pyinstaller({'m': 'X = 1'}, pyver=314))],
                     strings=[EXE + '!m'])
        self.assertIn('python 314', out['strings'][0]['refused'])
        out, _ = run([self.exe_layer(b'x')], strings=['/usr/local/bin!m', '/none!m'])
        self.assertEqual(out['strings'][0]['exe']['refused'], 'a dir, not a file')
        self.assertEqual(out['strings'][1]['exe'], {'path': '/none', 'present': False})

    def test_marshal_walk_refuses_what_it_does_not_know(self):
        data = marshal.dumps(compile('X = 1', 'f', 'exec'))
        for bad in (data[:len(data) // 2], b'c' + bytes(3), b'?'):
            with self.assertRaises((guest._PyiError, struct.error), msg=bad[:8]):
                guest._pyz_strings(bad)
        with self.assertRaises(guest._PyiError):
            guest._pyz_strings(marshal.dumps(('not', 'code')))


class Operation(unittest.TestCase):
    def test_cli_passes_text_requests(self):
        seen = []
        with mock.patch.object(guest, 'Context', side_effect=lambda p, s: ('ctx', p, s)), \
                mock.patch.object(guest, 'image_inspect',
                                  side_effect=lambda c, p, t=None: seen.append((c, p, t)) or
                                  {'operation': 'image-inspect', 'result': 'inspected'}), \
                contextlib.redirect_stdout(io.StringIO()):
            rc = guest.main(['image-inspect', '--profile', 'P', '--state-dir', 'S',
                             '--list', '/a/**', '--excerpt', '/a/b', '3', '9',
                             '--search', '/a/*', 'x+y', '--distinct', '/a/*', 'K_[A-Z]+',
                             '--strings', '/bin/s!m.*', '--context', '40', '--max-matches', '2'])
        self.assertEqual(rc, 0)
        (ctx, paths, parsed), = seen
        self.assertEqual((ctx, paths, parsed['context'], parsed['max_matches']),
                         (('ctx', 'P', 'S'), [], 40, 2))
        self.assertEqual([(r['op'], r.get('glob', r.get('path'))) for r in parsed['requests']],
                         [('list', '/a/**'), ('excerpt', '/a/b'), ('search', '/a/*'),
                          ('distinct', '/a/*'), ('strings', '/bin/s!m.*')])
        self.assertEqual((parsed['requests'][1]['start'], parsed['requests'][1]['end']), (3, 9))

    def cli_refusal(self, *argv):
        with mock.patch.object(guest, 'Context', side_effect=lambda p, s: ('ctx', p, s)), \
                mock.patch.object(guest, 'image_inspect', side_effect=AssertionError), \
                contextlib.redirect_stdout(io.StringIO()) as out, \
                contextlib.redirect_stderr(io.StringIO()):
            rc = guest.main(['image-inspect', '--profile', 'P', '--state-dir', 'S', *argv])
        self.assertEqual(rc, 1)
        return json.loads(out.getvalue())['message']

    def test_cli_refusals(self):
        self.assertIn('need a text request', self.cli_refusal('--path', '/a', '--context', '9'))
        self.assertIn('line numbers', self.cli_refusal('--excerpt', '/a', 'x', '2'))
        self.assertIn('empty string', self.cli_refusal('--search', '/a', 'z?'))

    def test_without_any_request_it_refuses(self):
        ctx = base.Operation.ctx(self, base.REPO / 'tools' / 'tests' / 'no-such-state-dir')
        with mock.patch.object(guest, 'open', create=True, side_effect=AssertionError):
            with self.assertRaises(guest.Refused) as caught:
                guest.image_inspect(ctx, [], text())
            self.assertIn('at least one --path or text request', str(caught.exception))
            with self.assertRaises(guest.Refused) as caught:
                guest.image_inspect(ctx, [])
            self.assertIn('needs 1 to', str(caught.exception))

    def test_reads_the_verified_stage_with_text(self):
        ctx = base.Operation.ctx(self, base.REPO / 'tools' / 'tests' / 'no-such-state-dir')
        data, image = archive([layer([F('acp/cli.js', b'ANTHROPIC_BASE_URL')])])
        image.update(repository='r', index_digest='i', manifest_digest='m')
        with mock.patch.object(guest.Path, 'is_dir', return_value=True), \
                mock.patch.object(guest, '_plain_dir'), \
                mock.patch.object(guest, 'provision_lock', return_value=({}, 'l.json', 'f' * 64)), \
                mock.patch.object(guest, 'provision_items', return_value=[]), \
                mock.patch.object(guest, 'provision_image', return_value=image), \
                mock.patch.object(guest, 'verify_staged', return_value={'files': 1}) as verify, \
                mock.patch.object(guest, 'open', create=True,
                                  side_effect=lambda p, m: io.BytesIO(data)):
            out = guest.image_inspect(ctx, [], text(searches=[('/acp/*', 'BASE_URL')]))
        verify.assert_called_once()
        self.assertEqual((out['result'], out['paths'],
                          out['text']['searches'][0]['matches_total']), ('inspected', [], 1))


if __name__ == '__main__':
    unittest.main()
