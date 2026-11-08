"""Tests for tools/guest.py provision-fetch (F-04.1a; stdlib unittest; no network, no guest).

Run from the repository root:  python -I -B -m unittest discover -s tools/tests -v

Every case builds a temporary repository copy of the profile whose provider.provision_lock
names a synthetic lock, serves its artifacts from an in-memory opener, and stands in a
fake crane for the registry. The committed lock is only read, never fetched.
"""
from pathlib import Path
import copy
import hashlib
import importlib.util
import io
import json
import os
import shutil
import tarfile
import tempfile
import unittest
from unittest import mock

CATEGORY = 'unit'

REPO = Path(__file__).resolve().parents[2]
PROFILE_NAME = 'strong-windows-qemu-whpx'
PROFILE_DIR = REPO / 'profiles' / PROFILE_NAME

_spec = importlib.util.spec_from_file_location('guest', REPO / 'tools' / 'guest.py')
guest = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guest)

_cspec = importlib.util.spec_from_file_location('check_profile', REPO / 'tools' / 'check_profile.py')
check_profile = importlib.util.module_from_spec(_cspec)
_cspec.loader.exec_module(check_profile)

TS = '20261106T143859Z'
SNAP = 'https://snapshot.debian.org/archive/'
REPOSITORY = 'ghcr.io/openhands/agent-server'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def digest(data):
    return 'sha256:' + sha(data)


def tar_bytes(members, gz=False):
    """members: [(name, bytes)] as regular files."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz' if gz else 'w') as tf:
        for name, data in members:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class Fixture:
    """A synthetic, self-consistent set of upstream artifacts and the lock pinning them."""

    def __init__(self):
        self.inrelease = b'-----signed InRelease (synthetic)-----\n'
        self.packages = b'synthetic Packages.xz bytes'
        self.debs = {'tini_0.19.0-3+b8_amd64.deb': b'deb tini',
                     'docker.io_26.1.5+dfsg1-9+deb13u1_amd64.deb': b'deb docker.io'}
        self.binary = b'agent-server binary'
        self.crane_exe = b'MZ fake crane'
        self.crane_tgz = tar_bytes([('LICENSE', b'Apache'), ('crane.exe', self.crane_exe)], gz=True)
        self.config = b'{"architecture":"amd64","os":"linux"}'
        self.layer_a, self.layer_b = b'layer a bytes', b'layer b bytes'
        # a duplicate layer, as in the real image (the empty layer appears three times)
        self.layer_list = [self.layer_a, self.layer_b, self.layer_a]
        self.manifest = json.dumps({
            'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.manifest.v1+json',
            'config': {'digest': digest(self.config), 'size': len(self.config)},
            'layers': [{'digest': digest(l), 'size': len(l)} for l in self.layer_list]}).encode()
        self.index = json.dumps({'schemaVersion': 2, 'manifests': [
            {'digest': digest(self.manifest), 'platform': {'os': 'linux', 'architecture': 'amd64'}},
            {'digest': 'sha256:' + 'a' * 64, 'platform': {'os': 'unknown', 'architecture': 'unknown'}},
            {'digest': 'sha256:' + 'b' * 64, 'platform': {'os': 'linux', 'architecture': 'arm64'}},
        ]}).encode()
        self.urls = {}
        base = f'{SNAP}debian/{TS}/'
        files = []
        for path, data in (('dists/trixie/InRelease', self.inrelease),
                           ('dists/trixie/main/binary-amd64/Packages.xz', self.packages)):
            files.append({'path': path, 'url': base + path, 'size': len(data), 'sha256': sha(data)})
            self.urls[base + path] = data
        packages = []
        for name, data in self.debs.items():
            url = f'{base}pool/main/x/{name}'
            packages.append({'name': name.split('_')[0], 'version': name.split('_')[1],
                             'filename': name, 'url': url, 'size': len(data), 'sha256': sha(data)})
            self.urls[url] = data
        bin_url = 'https://github.com/OpenHands/software-agent-sdk/releases/download/v1.60.1/agent-server-1.60.1-linux-x86_64'
        crane_url = 'https://github.com/google/go-containerregistry/releases/download/v0.22.1/go-containerregistry_Windows_x86_64.tar.gz'
        self.urls[bin_url] = self.binary
        self.urls[crane_url] = self.crane_tgz
        index_digest = digest(self.index)
        self.lock = {
            'schema': guest.PROVISION_LOCK_SCHEMA, 'profile': PROFILE_NAME,
            'debian': {'snapshot': {'timestamp': TS},
                       'suites': [{'archive': 'debian', 'suite': 'trixie', 'base_url': base,
                                   'files': files}],
                       'packages': packages},
            'image': {'repository': REPOSITORY, 'ref': f'{REPOSITORY}@{index_digest}',
                      'index_digest': index_digest, 'platform': 'linux/amd64',
                      'manifest_digest': digest(self.manifest),
                      'config_digest': digest(self.config), 'config_size': len(self.config),
                      'image_id': digest(self.config),
                      'layers': [{'digest': digest(l), 'size': len(l)} for l in self.layer_list]},
            'release_binary': {'name': 'agent-server-1.60.1-linux-x86_64', 'url': bin_url,
                               'size': len(self.binary), 'sha256': sha(self.binary)},
            'tools': {'crane': {'version': 'v0.22.1', 'asset': 'go-containerregistry_Windows_x86_64.tar.gz',
                                'url': crane_url, 'size': len(self.crane_tgz), 'sha256': sha(self.crane_tgz),
                                'checksums_source': {'url': 'https://example.invalid/checksums.txt'},
                                'member': {'name': 'crane.exe', 'size': len(self.crane_exe),
                                           'sha256': sha(self.crane_exe)}}},
        }

    def archive(self, config=None):
        """The docker-archive crane pull writes: manifest.json, the config, distinct layers."""
        config = self.config if config is None else config
        cfg_name = digest(config)
        names = [f'{sha(l)}.tar.gz' for l in self.layer_list]
        members = [('manifest.json', json.dumps([{'Config': cfg_name, 'RepoTags': [],
                                                  'Layers': names}]).encode()),
                   (cfg_name, config)]
        seen = set()
        for name, data in zip(names, self.layer_list):
            if name not in seen:
                seen.add(name)
                members.append((name, data))
        return tar_bytes(members)


class FakeResponse(io.BytesIO):
    def __init__(self, data, url):
        super().__init__(data)
        self._url = url

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class FakeOpener:
    def __init__(self, urls):
        self.urls = dict(urls)
        self.calls = []

    def open(self, request, timeout=None):
        url = request.full_url
        self.calls.append(url)
        if url not in self.urls:
            raise guest.urllib.error.URLError(f'no such url {url}')
        return FakeResponse(self.urls[url], url)


class FakeCrane:
    def __init__(self, fixture, archive=None, manifests=None):
        self.fixture = fixture
        self.archive = fixture.archive() if archive is None else archive
        self.manifests = manifests or {digest(fixture.index): fixture.index,
                                       digest(fixture.manifest): fixture.manifest}
        self.calls = []

    def __call__(self, exe, args, env):
        self.calls.append(list(args))
        # crane must run from its verified install, with an empty, private home
        assert Path(exe).read_bytes() == self.fixture.crane_exe
        assert env['DOCKER_CONFIG'] == env['USERPROFILE'] == env['HOME']
        assert os.listdir(env['DOCKER_CONFIG']) == []
        assert not ({'HTTPS_PROXY', 'PATH', 'APPDATA'} & set(env))
        if args[0] == 'manifest':
            ref = args[1].split('@', 1)[1]
            return (0, self.manifests[ref], '') if ref in self.manifests else (1, b'', 'not found')
        if args[0] == 'pull':
            assert args[1:3] == ['--platform', 'linux/amd64']
            assert args[3] == self.fixture.lock['image']['ref']
            Path(args[4]).write_bytes(self.archive)
            return 0, b'', ''
        return 2, b'', 'unexpected'


class ProvisionFetch(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-provision-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        home = self.tmp / 'home'
        home.mkdir()
        patcher = mock.patch.dict(os.environ, {'USERPROFILE': str(home), 'HOME': str(home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        quiet = mock.patch.object(guest, 'log')
        quiet.start()
        self.addCleanup(quiet.stop)
        self.state = self.tmp / 'state'
        self.state.mkdir()
        self.fx = Fixture()
        self.write_lock(self.fx.lock)

    def write_lock(self, lock, pin=None):
        pdir = self.tmp / 'repo' / 'profiles' / PROFILE_NAME
        pdir.mkdir(parents=True, exist_ok=True)
        data = (json.dumps(lock, indent=2) + '\n').encode()
        (pdir / 'provision.lock.json').write_bytes(data)
        profile = json.loads((PROFILE_DIR / 'profile.json').read_text(encoding='utf-8'))
        profile['provider']['provision_lock'] = {
            'path': f'profiles/{PROFILE_NAME}/provision.lock.json', 'sha256': pin or sha(data)}
        (pdir / 'profile.json').write_text(json.dumps(profile, indent=2), encoding='utf-8')
        self.lock_sha = sha(data)

    def ctx(self):
        return guest.Context(str(self.tmp / 'repo' / 'profiles' / PROFILE_NAME), str(self.state))

    def fetch(self, opener=None, crane=None):
        self.opener = opener or FakeOpener(self.fx.urls)
        self.crane = crane or FakeCrane(self.fx)
        return guest.provision_fetch(self.ctx(), self.opener, self.crane)

    def refused(self, code, **kw):
        with self.assertRaises(guest.Refused) as caught:
            self.fetch(**kw)
        self.assertEqual(caught.exception.code, code, str(caught.exception))
        self.assertFalse((self.state / 'provision' / self.lock_sha).exists(),
                         'nothing may be staged after a refusal')
        return caught.exception

    # --- positive
    def test_stages_every_artifact_atomically(self):
        result = self.fetch()
        self.assertEqual(result['result'], 'staged')
        staged = self.state / 'provision' / self.lock_sha
        self.assertFalse((self.state / 'provision' / f'{self.lock_sha}.partial').exists())
        manifest = json.loads((staged / 'staged.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['lock']['sha256'], self.lock_sha)
        paths = sorted(f['path'] for f in manifest['files'])
        self.assertEqual(paths, sorted([
            'agent-server/agent-server-1.60.1-linux-x86_64',
            'debs/docker.io_26.1.5+dfsg1-9+deb13u1_amd64.deb', 'debs/tini_0.19.0-3+b8_amd64.deb',
            'image/agent-server.tar', 'image/index.json', 'image/manifest.json',
            'index/debian/dists/trixie/InRelease',
            'index/debian/dists/trixie/main/binary-amd64/Packages.xz']))
        self.assertEqual(guest.staged_inventory(staged), sorted(paths + ['staged.json']))
        crane = self.state / 'tools' / 'crane' / 'v0.22.1'
        self.assertEqual(os.listdir(crane), ['crane.exe'])         # the archive is removed
        self.assertEqual(result['crane']['state'], 'installed')
        self.assertEqual(result['image']['pull']['verify']['distinct_layers'], 2)
        self.assertEqual(result['image']['pull']['verify']['layers'], 3)
        self.assertEqual(len(os.listdir(self.state / 'provision' / 'records')), 1)
        # a redirect target may be a pre-signed URL: only its host is recorded
        self.assertEqual({d.get('final_host') for d in result['downloads']},
                         {'snapshot.debian.org', 'github.com'})
        self.assertNotIn('final_url', json.dumps(result))

    def test_second_run_reverifies_and_reuses(self):
        self.fetch()
        result = self.fetch()
        self.assertEqual(result['result'], 'reused')
        self.assertEqual(self.opener.calls, [])
        self.assertEqual(self.crane.calls, [])
        self.assertEqual(result['verify']['files'], 8)

    def test_resumes_an_interrupted_run(self):
        work = self.state / 'provision' / f'{self.lock_sha}.partial' / 'debs'
        work.mkdir(parents=True)
        (work / 'tini_0.19.0-3+b8_amd64.deb').write_bytes(self.fx.debs['tini_0.19.0-3+b8_amd64.deb'])
        (work / 'docker.io_26.1.5+dfsg1-9+deb13u1_amd64.deb.part').write_bytes(b'half')
        result = self.fetch()
        states = {d['path']: d['state'] for d in result['downloads']}
        self.assertEqual(states['debs/tini_0.19.0-3+b8_amd64.deb'], 'reused')
        self.assertEqual(states['debs/docker.io_26.1.5+dfsg1-9+deb13u1_amd64.deb'], 'fetched')
        self.assertEqual(result['result'], 'staged')
        self.assertNotIn('debs/docker.io_26.1.5+dfsg1-9+deb13u1_amd64.deb.part',
                         guest.staged_inventory(self.state / 'provision' / self.lock_sha))

    # --- negative controls
    def test_tampered_deb_refuses(self):
        urls = dict(self.fx.urls)
        url = self.fx.lock['debian']['packages'][1]['url']
        urls[url] = b'deb docker.iX'                        # same size, different bytes
        exc = self.refused('HASH_MISMATCH', opener=FakeOpener(urls))
        kept = Path(exc.detail['kept'])
        self.assertTrue(kept.name.endswith('.deb.rejected'))
        self.assertEqual(kept.read_bytes(), b'deb docker.iX')

    def test_oversized_download_refuses(self):
        urls = dict(self.fx.urls)
        urls[self.fx.lock['release_binary']['url']] = self.fx.binary + b'!'
        self.refused('HASH_MISMATCH', opener=FakeOpener(urls))

    def test_wrong_locked_image_config_digest_refuses(self):
        lock = copy.deepcopy(self.fx.lock)
        lock['image']['config_digest'] = lock['image']['image_id'] = 'sha256:' + 'c' * 64
        self.write_lock(lock)
        self.refused('DIGEST_MISMATCH')
        self.assertEqual([c[0] for c in self.crane.calls], ['manifest', 'manifest'])

    def test_pulled_archive_with_another_config_refuses(self):
        crane = FakeCrane(self.fx, archive=self.fx.archive(config=b'{"other":"config"}'))
        self.refused('IMAGE_MISMATCH', crane=crane)
        rejected = self.state / 'provision' / f'{self.lock_sha}.partial' / 'image' / \
            'agent-server.tar.rejected'
        self.assertTrue(rejected.is_file())

    def test_index_bytes_not_matching_the_locked_digest_refuse(self):
        manifests = {digest(self.fx.index): self.fx.index + b' ',
                     digest(self.fx.manifest): self.fx.manifest}
        self.refused('DIGEST_MISMATCH', crane=FakeCrane(self.fx, manifests=manifests))

    def test_index_naming_another_platform_manifest_refuses(self):
        lock = copy.deepcopy(self.fx.lock)
        lock['image']['manifest_digest'] = 'sha256:' + 'b' * 64
        self.write_lock(lock)
        self.refused('DIGEST_MISMATCH')

    def test_tampered_crane_refuses_before_any_use(self):
        lock = copy.deepcopy(self.fx.lock)
        lock['tools']['crane']['member']['sha256'] = '0' * 64
        self.write_lock(lock)
        self.refused('HASH_MISMATCH')
        self.assertEqual(self.crane.calls, [])
        self.assertFalse((self.state / 'tools' / 'crane' / 'v0.22.1' / 'crane.exe').exists())

    def test_installed_crane_that_changed_refuses(self):
        exe = self.state / 'tools' / 'crane' / 'v0.22.1' / 'crane.exe'
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b'MZ something else')
        self.refused('HASH_MISMATCH')
        self.assertEqual(self.crane.calls, [])

    def test_lock_not_matching_the_profile_pin_refuses(self):
        self.write_lock(self.fx.lock, pin='0' * 64)
        self.refused('LOCK_MISMATCH')

    def test_non_https_url_refuses_before_any_download(self):
        lock = copy.deepcopy(self.fx.lock)
        lock['release_binary']['url'] = 'http://example.invalid/agent-server'
        self.write_lock(lock)
        self.refused('REFUSED')
        self.assertEqual(self.opener.calls, [])

    def test_unsafe_filename_refuses(self):
        lock = copy.deepcopy(self.fx.lock)
        lock['debian']['packages'][0]['filename'] = '../escape.deb'
        self.write_lock(lock)
        self.refused('REFUSED')

    def test_staged_file_changed_after_staging_refuses_reuse(self):
        self.fetch()
        staged = self.state / 'provision' / self.lock_sha
        deb = staged / 'debs' / 'tini_0.19.0-3+b8_amd64.deb'
        deb.write_bytes(b'deb tinX')
        with self.assertRaises(guest.Refused) as caught:
            self.fetch()
        self.assertEqual(caught.exception.code, 'STAGED_MISMATCH')

    def test_extra_file_in_staged_dir_refuses_reuse(self):
        self.fetch()
        (self.state / 'provision' / self.lock_sha / 'debs' / 'extra.deb').write_bytes(b'x')
        with self.assertRaises(guest.Refused) as caught:
            self.fetch()
        self.assertEqual(caught.exception.code, 'STAGED_MISMATCH')

    def test_archive_with_an_extra_member_refuses(self):
        path = self.tmp / 'a.tar'
        data = self.fx.archive()
        with tarfile.open(fileobj=io.BytesIO(data)) as src, tarfile.open(path, 'w') as dst:
            for m in src.getmembers():
                dst.addfile(m, src.extractfile(m))
            info = tarfile.TarInfo('extra')
            info.size = 1
            dst.addfile(info, io.BytesIO(b'x'))
        with self.assertRaises(guest.Refused) as caught:
            guest.verify_image_tar(path, self.fx.lock['image'])
        self.assertEqual(caught.exception.code, 'IMAGE_MISMATCH')

    def test_crane_env_drops_the_callers_settings(self):
        env = guest.crane_env('H', 'T', environ={'SYSTEMROOT': 'C:\\W', 'HTTPS_PROXY': 'x',
                                                  'DOCKER_CONFIG': 'C:\\Users\\o\\.docker',
                                                  'USERPROFILE': 'C:\\Users\\o', 'PATH': 'p'})
        self.assertEqual(env, {'SYSTEMROOT': 'C:\\W', 'DOCKER_CONFIG': 'H', 'USERPROFILE': 'H',
                               'HOME': 'H', 'TEMP': 'T', 'TMP': 'T'})


class CommittedLock(unittest.TestCase):
    """The committed provision lock, read only: shape, consistency, no fetch."""
    category = 'contract'

    def setUp(self):
        self.profile = json.loads((PROFILE_DIR / 'profile.json').read_text(encoding='utf-8'))
        entry = self.profile['provider']['provision_lock']
        self.data = (REPO / entry['path']).read_bytes()
        self.lock = json.loads(self.data)
        self.entry = entry

    def test_profile_pins_the_lock(self):
        self.assertEqual(sha(self.data), self.entry['sha256'])

    def test_static_shape(self):
        self.assertEqual(check_profile.provision_lock_problems(self.lock, PROFILE_NAME), [])
        items = guest.provision_items(self.lock)
        image = guest.provision_image(self.lock)
        self.assertEqual(sorted(p['name'] for p in self.lock['debian']['packages']),
                         ['containerd', 'docker-cli', 'docker.io', 'runc', 'tini'])
        self.assertEqual(len(items), 4 + 5 + 1)
        self.assertEqual(image['layers_total_bytes'], sum(l['size'] for l in image['layers']))

    def test_components_lock_agrees(self):
        components = json.loads((REPO / 'composition' / 'lock' / 'components.lock.json')
                                .read_text(encoding='utf-8'))['conversation_image']
        image = self.lock['image']
        self.assertEqual(components['index_digest'], image['index_digest'])
        self.assertEqual(components['ref'], image['ref'])
        self.assertEqual(components['platform_digests']['linux/amd64'], image['manifest_digest'])
        self.assertEqual(components['config_digests']['linux/amd64'], image['config_digest'])


if __name__ == '__main__':
    unittest.main()
