"""Tests for tools/guest.py image-inspect (S-03.3; stdlib unittest; no network, no guest).

Run from the repository root:  python -I -B -m unittest discover -s tools/tests -v

Every docker-archive is synthetic and built in memory: no temporary directory, no file
written, no process launched. The committed profile and provision lock are only read.
"""
from pathlib import Path
import contextlib
import hashlib
import io
import json
import sys
import tarfile
import unittest
from unittest import mock

CATEGORY = 'unit'

REPO = Path(__file__).resolve().parents[2]
PROFILE_DIR = REPO / 'profiles' / 'strong-windows-qemu-whpx'

# Shared compiled code for the modules loaded from files (plan leaf F-09): module_code.load is
# spec_from_file_location and exec_module, with each file compiled once per process.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import module_code  # noqa: E402
guest = module_code.load('guest', REPO / 'tools' / 'guest.py')


def digest(data):
    return 'sha256:' + hashlib.sha256(data).hexdigest()


def F(name, data=b'', mode=0o644, uid=0, gid=0):
    return ('file', name, data, mode, uid, gid)


def D(name, mode=0o755):
    return ('dir', name, None, mode, 0, 0)


def S(name, target):
    return ('symlink', name, target, 0o777, 0, 0)


def H(name, target):
    return ('hardlink', name, target, 0o644, 0, 0)


def layer(entries, gz=True):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz' if gz else 'w') as tf:
        for kind, name, value, mode, uid, gid in entries:
            info = tarfile.TarInfo(name)
            info.mode, info.uid, info.gid = mode, uid, gid
            if kind == 'file':
                info.size = len(value)
                tf.addfile(info, io.BytesIO(value))
                continue
            info.type = {'dir': tarfile.DIRTYPE, 'symlink': tarfile.SYMTYPE,
                         'hardlink': tarfile.LNKTYPE}[kind]
            if kind != 'dir':
                info.linkname = value
            tf.addfile(info)
    return buf.getvalue()


def archive(layers, config=None):
    """A docker-archive as crane pull writes it, and the lock's image entry that pins it."""
    config = json.dumps(config or {'architecture': 'amd64', 'os': 'linux'}).encode()
    names = [digest(l)[7:] + '.tar.gz' for l in layers]
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w') as tf:
        members = [('manifest.json', json.dumps([{'Config': digest(config), 'RepoTags': [],
                                                  'Layers': names}]).encode()),
                   (digest(config), config)]
        seen = set()
        for name, data in zip(names, layers):
            if name not in seen:
                seen.add(name)
                members.append((name, data))
        for name, data in members:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    image = {'config_digest': digest(config),
             'layers': [{'digest': digest(l), 'size': len(l)} for l in layers]}
    return buf.getvalue(), image


def specs(*paths):
    return [guest.parse_image_path_spec(p) for p in paths]


def read(layers, *paths, config=None):
    data, image = archive(layers, config)
    out = guest.read_image_archive(io.BytesIO(data), image, specs(*paths))
    return {r['path'] + ('#' + r['selector'] if 'selector' in r else ''): r
            for r in out['paths']}, out


class UnionView(unittest.TestCase):
    def test_whiteout_and_opaque_directory_hide_lower_entries(self):
        l0 = layer([D('a'), F('a/keep', b'k'), F('a/gone', b'g'), D('d'), F('d/old1'),
                    D('d/sub'), F('d/sub/old2')])
        l1 = layer([F('a/.wh.gone'), D('d'), F('d/.wh..wh..opq'), F('d/new', b'n')])
        got, _ = read([l0, l1], '/a/keep', '/a/gone', '/d/old1', '/d/sub/old2', '/d/new', '/d')
        self.assertEqual(got['/a/keep']['layer'], 0)
        self.assertEqual(got['/a/keep']['sha256'], digest(b'k')[7:])
        for gone in ('/a/gone', '/d/old1', '/d/sub/old2'):
            self.assertEqual(got[gone], {'path': gone, 'present': False})
        self.assertEqual((got['/d/new']['layer'], got['/d/new']['type']), (1, 'file'))
        self.assertEqual(got['/d']['children'], ['new'])
        self.assertEqual(got['/d']['layer'], 1)

    def test_symlink_chain_resolves_inside_the_image(self):
        l0 = layer([D('usr'), D('usr/lib'), F('usr/lib/node', b'node', mode=0o755, uid=1, gid=2),
                    D('usr/bin'), S('usr/bin/n', '../lib/node'), S('bin', 'usr/bin'),
                    D('usr/local'), D('usr/local/bin'), S('usr/local/bin/w', '/bin/n')])
        got, _ = read([l0], '/usr/local/bin/w', '/bin/n')
        w = got['/usr/local/bin/w']
        self.assertEqual((w['present'], w['type'], w['link_target']), (True, 'symlink', '/bin/n'))
        self.assertEqual([h['path'] for h in w['links']], ['/usr/local/bin/w', '/bin', '/usr/bin/n'])
        self.assertEqual(w['real_path'], '/usr/lib/node')
        self.assertEqual(w['resolved'], {'path': '/usr/lib/node', 'type': 'file', 'mode': '0755',
                                         'uid': 1, 'gid': 2, 'size': 4, 'layer': 0})
        self.assertEqual(w['sha256'], digest(b'node')[7:])
        # a parent component that is a symlink is followed; the entry itself is not
        self.assertEqual(got['/bin/n']['type'], 'symlink')
        self.assertEqual(got['/bin/n']['links'][0], {'path': '/bin', 'target': 'usr/bin'})

    def test_hard_link_keeps_the_content_it_was_linked_to(self):
        l0 = layer([F('f', b'old'), H('h', 'f'), F('x', b'1')], gz=False)   # a plain tar layer
        l1 = layer([F('f', b'new'), F('x', b'2')])
        got, _ = read([l0, l1], '/h', '/f', '/x')
        self.assertEqual(got['/h']['hardlink_to'], '/f')
        self.assertEqual(got['/h']['sha256'], digest(b'old')[7:])
        self.assertEqual((got['/f']['sha256'], got['/f']['layer']), (digest(b'new')[7:], 1))
        self.assertEqual((got['/x']['sha256'], got['/x']['layer']), (digest(b'2')[7:], 1))

    def test_symlink_escaping_the_root_is_refused(self):
        l0 = layer([S('esc', '../../etc'), D('etc'), F('etc/passwd', b'p')])
        got, _ = read([l0], '/esc', '/esc/passwd')
        self.assertEqual((got['/esc']['present'], got['/esc']['refused']),
                         (True, 'escapes the image root'))
        self.assertNotIn('sha256', got['/esc'])
        self.assertEqual((got['/esc/passwd']['present'], got['/esc/passwd']['refused']),
                         (False, 'escapes the image root'))

    def test_symlink_loop_is_bounded(self):
        got, _ = read([layer([S('a', 'b'), S('b', '/a')])], '/a')
        self.assertIn('symlink hops', got['/a']['refused'])
        self.assertEqual(len(got['/a']['links']), guest.IMAGE_INSPECT_MAX_HOPS)

    def test_file_replacing_a_directory_drops_its_children(self):
        l0 = layer([D('p'), F('p/c')])
        l1 = layer([S('p', 'q')])
        got, _ = read([l0, l1], '/p/c', '/p')
        self.assertEqual(got['/p/c']['present'], False)
        self.assertEqual((got['/p']['type'], got['/p']['dangling']), ('symlink', True))
        # a directory made again later starts empty: the old children stay gone
        got, _ = read([l0, l1, layer([D('p')])], '/p/c', '/p')
        self.assertEqual(got['/p/c'], {'path': '/p/c', 'present': False})
        self.assertEqual((got['/p']['children'], got['/p']['layer']), ([], 2))

    def test_json_field_selector(self):
        pkg = json.dumps({'version': '0.63.0', 'bin': {'claude-agent-acp': 'dist/index.js'},
                          'files': ['dist']}).encode()
        got, _ = read([layer([F('pkg/package.json', pkg), F('pkg/plain', b'not json')])],
                      '/pkg/package.json#version', '/pkg/package.json#bin#claude-agent-acp',
                      '/pkg/package.json#files#0', '/pkg/package.json#nope', '/pkg/plain#version',
                      '/pkg#version')
        self.assertEqual(got['/pkg/package.json#version']['value'], '0.63.0')
        self.assertEqual(got['/pkg/package.json#version']['sha256'], digest(pkg)[7:])
        self.assertEqual(got['/pkg/package.json#bin#claude-agent-acp']['value'], 'dist/index.js')
        self.assertEqual(got['/pkg/package.json#files#0']['value'], 'dist')
        self.assertEqual(got['/pkg/package.json#nope']['field_error'], 'no field nope')
        self.assertIn('not JSON', got['/pkg/plain#version']['field_error'])
        self.assertIn('not a file', got['/pkg#version']['field_error'])

    def test_absent_path_and_root_listing(self):
        got, out = read([layer([F('one'), D('two')])], '/nope', '/')
        self.assertEqual(got['/nope'], {'path': '/nope', 'present': False})
        self.assertEqual(got['/']['children'], ['one', 'two'])
        self.assertEqual(out['anomalies'], {'count': 0, 'examples': []})

    def test_config_env_and_history(self):
        config = {'config': {'User': 'openhands', 'Entrypoint': ['/usr/bin/tini'],
                             'Env': ['PATH=/usr/local/bin:/usr/bin', 'ACP_NODE_DIR=/acp-node',
                                     'OH_ACP_SKILL_SOURCING=openhands_managed', 'LANG=C.UTF-8']},
                  'history': [{'created_by': 'ADD rootfs'},
                              {'created_by': 'ENV ACP_NODE_DIR=/acp-node', 'empty_layer': True},
                              {'created_by': 'COPY /acp-node /acp-node # buildkit'},
                              {'created_by': 'RUN echo ' + 'x' * 500 + ' codex'}]}
        _, out = read([layer([F('a')]), layer([F('b')]), layer([F('c')])], '/a', config=config)
        cfg = out['config']
        self.assertEqual(cfg['env'], ['PATH=/usr/local/bin:/usr/bin', 'ACP_NODE_DIR=/acp-node',
                                      'OH_ACP_SKILL_SOURCING=openhands_managed'])
        self.assertEqual((cfg['user'], cfg['history_total'], cfg['history_layers_match']),
                         ('openhands', 4, True))
        self.assertEqual([(h['history'], h['layer']) for h in cfg['history_matches']],
                         [(1, None), (2, 1), (3, 2)])
        self.assertTrue(cfg['history_matches'][2]['truncated'])
        self.assertEqual(len(cfg['history_matches'][2]['created_by']),
                         guest.IMAGE_INSPECT_MAX_HISTORY)
        self.assertEqual(cfg['layer_steps'][1], 'COPY /acp-node /acp-node # buildkit')


class LockAndFormat(unittest.TestCase):
    def refused(self, code, data, image, *paths):
        with self.assertRaises(guest.Refused) as caught:
            guest.read_image_archive(io.BytesIO(data), image, specs(*(paths or ('/a',))))
        self.assertEqual(caught.exception.code, code, str(caught.exception))
        return caught.exception

    def test_layer_not_matching_the_lock_is_refused(self):
        l0 = layer([F('a')])
        data, image = archive([l0])
        image['layers'][0]['digest'] = 'sha256:' + 'c' * 64
        self.refused('IMAGE_MISMATCH', data, image)

    def test_config_not_matching_the_lock_is_refused(self):
        data, image = archive([layer([F('a')])])
        image['config_digest'] = 'sha256:' + 'd' * 64
        self.refused('IMAGE_MISMATCH', data, image)

    def test_synthetic_archive_against_the_committed_lock_is_refused(self):
        lock = json.loads((PROFILE_DIR / 'provision.lock.json').read_text(encoding='utf-8'))
        data, _ = archive([layer([F('a')])])
        self.refused('IMAGE_MISMATCH', data, guest.provision_image(lock))

    def test_layer_that_is_not_a_tar_is_refused(self):
        data, image = archive([b'not a tar stream at all' * 30])
        self.refused('IMAGE_FORMAT', data, image)

    def test_member_leaving_the_root_is_refused(self):
        data, image = archive([layer([F('../x')])])
        self.refused('IMAGE_FORMAT', data, image)

    def test_path_specs(self):
        self.assertEqual(guest.parse_image_path_spec('/p/package.json#bin#x'),
                         {'spec': '/p/package.json#bin#x', 'path': '/p/package.json',
                          'selector': ['bin', 'x']})
        for bad in ('relative/path', '/p#', '/p##x', '/p\0'):
            with self.assertRaises(guest.Refused):
                guest.parse_image_path_spec(bad)


class Operation(unittest.TestCase):
    """image_inspect locates the stage of the profile's lock and re-verifies it first."""

    def ctx(self, state):
        with mock.patch.object(guest, 'check_state_dir', return_value=state):
            return guest.Context(str(PROFILE_DIR), str(state))

    def test_without_a_stage_it_refuses(self):
        ctx = self.ctx(REPO / 'tools' / 'tests' / 'no-such-state-dir')
        with mock.patch.object(guest, 'open', create=True, side_effect=AssertionError):
            with self.assertRaises(guest.Refused) as caught:
                guest.image_inspect(ctx, ['/a'])
        self.assertIn('no stage for this lock', str(caught.exception))

    def test_a_stage_failing_verification_is_never_read(self):
        ctx = self.ctx(REPO / 'tools' / 'tests' / 'no-such-state-dir')
        failing = guest.Refused('STAGED_MISMATCH', 'tampered')
        with mock.patch.object(guest.Path, 'is_dir', return_value=True), \
                mock.patch.object(guest, '_plain_dir'), \
                mock.patch.object(guest, 'verify_staged', side_effect=failing) as verify, \
                mock.patch.object(guest, 'open', create=True, side_effect=AssertionError):
            with self.assertRaises(guest.Refused) as caught:
                guest.image_inspect(ctx, ['/a'])
        self.assertEqual(caught.exception.code, 'STAGED_MISMATCH')
        profile_text = PROFILE_DIR.joinpath('profile.json').read_text(encoding='utf-8')
        self.assertIn(Path(verify.call_args.args[0]).name, profile_text)  # the pinned lock sha

    def test_reads_the_verified_stage(self):
        ctx = self.ctx(REPO / 'tools' / 'tests' / 'no-such-state-dir')
        data, image = archive([layer([F('acp-node/bin/node', b'ELF')])])
        image.update(repository='ghcr.io/openhands/agent-server', index_digest='i',
                     manifest_digest='m')
        opened = []

        def fake_open(path, mode):
            opened.append((Path(path).parts[-3:], mode))
            return io.BytesIO(data)
        with mock.patch.object(guest.Path, 'is_dir', return_value=True), \
                mock.patch.object(guest, '_plain_dir'), \
                mock.patch.object(guest, 'provision_lock', return_value=({}, 'l.json', 'f' * 64)), \
                mock.patch.object(guest, 'provision_items', return_value=[]), \
                mock.patch.object(guest, 'provision_image', return_value=image), \
                mock.patch.object(guest, 'verify_staged', return_value={'files': 1}), \
                mock.patch.object(guest, 'open', create=True, side_effect=fake_open):
            out = guest.image_inspect(ctx, ['/acp-node/bin/node', '/usr/local/bin/codex-acp'])
        self.assertEqual(opened, [(('f' * 64, 'image', 'agent-server.tar'), 'rb')])
        self.assertEqual((out['operation'], out['result'], out['verify']),
                         ('image-inspect', 'inspected', {'files': 1}))
        self.assertEqual([p['present'] for p in out['paths']], [True, False])
        self.assertEqual(out['paths'][0]['sha256'], digest(b'ELF')[7:])

    def test_path_count_is_bounded(self):
        ctx = self.ctx(REPO / 'tools' / 'tests' / 'no-such-state-dir')
        with self.assertRaises(guest.Refused):
            guest.image_inspect(ctx, ['/a'] * (guest.IMAGE_INSPECT_MAX_PATHS + 1))

    def test_cli_wiring(self):
        seen = []
        with mock.patch.object(guest, 'Context', side_effect=lambda p, s: ('ctx', p, s)), \
                mock.patch.object(guest, 'image_inspect',
                                  side_effect=lambda c, p: seen.append((c, p)) or
                                  {'operation': 'image-inspect', 'result': 'inspected'}), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            rc = guest.main(['image-inspect', '--profile', 'P', '--state-dir', 'S',
                             '--path', '/a', '--path', '/b#version'])
        self.assertEqual(rc, 0)
        self.assertEqual(seen, [(('ctx', 'P', 'S'), ['/a', '/b#version'])])
        self.assertEqual(json.loads(out.getvalue())['result'], 'inspected')


if __name__ == '__main__':
    unittest.main()
