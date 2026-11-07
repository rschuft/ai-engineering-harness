"""Tests for the guest side of provisioning (F-04.1b; stdlib unittest; no guest, no network).

Run from the repository root:  python -I -B -m unittest discover -s tools/tests -v

- The seeded root step: the committed user-data template carries the script and the three
  units; the script is parsed (never run: it is Linux-only and needs root) and its paths,
  its step sequence and its daemon.json source are compared with the profile.
- create --provision's manifest, built from a synthetic lock staged by provision-fetch
  with fakes (the fixtures of test_provision_fetch.py).
- The provision operation against a fake SSH and SFTP that stand for the guest: bounds,
  refusals, the READY marker, the fetched RESULT.json and its checks.
- smoke --provision and the CLI wiring.
"""
from pathlib import Path
import ast
import base64
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
PROFILE_NAME = 'strong-windows-qemu-whpx'
PROFILE_DIR = REPO / 'profiles' / PROFILE_NAME


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fetch_tests = _load('aieh_test_provision_fetch', REPO / 'tools' / 'tests' / 'test_provision_fetch.py')
guest = fetch_tests.guest          # one module instance shared with the fixtures
nocloud_seed = _load('aieh_nocloud_seed', REPO / 'tools' / 'nocloud_seed.py')
PROFILE = json.loads((PROFILE_DIR / 'profile.json').read_text(encoding='utf-8'))
PCONF = PROFILE['provisioning']
TEMPLATE = (REPO / 'profiles' / 'seed' / 'user-data.tmpl').read_text(encoding='utf-8')
ARCHIVE_TAG = 'ghcr.io/openhands/agent-server:i-was-a-digest'


def write_file_entries(text):
    """{path: content} of the template's write_files block scalars (two-space list items,
    six-space content), read without a YAML parser."""
    out, path, body, in_body = {}, None, [], False
    for line in text.split('\n'):
        if line.startswith('  - path: '):
            if path:
                out[path] = '\n'.join(body)
            path, body, in_body = line[len('  - path: '):], [], False
        elif path and line.startswith('    content: |'):
            in_body = True
        elif path and in_body and (line.startswith('      ') or line == ''):
            body.append(line[6:])
        elif path and in_body:
            out[path], path, in_body = '\n'.join(body), None, False
    if path:
        out[path] = '\n'.join(body)
    return {k: v.rstrip('\n') + '\n' for k, v in out.items()}


FILES = write_file_entries(TEMPLATE)
SCRIPT = FILES['/usr/local/sbin/aieh-provision']


def script_constants():
    tree = ast.parse(SCRIPT)
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and \
                isinstance(node.targets[0], ast.Name):
            try:
                out[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                pass
    return out


def unit(name):
    lines = FILES[f'/etc/systemd/system/{name}'].splitlines()
    return [line for line in lines if '=' in line]


class SeededRootStep(unittest.TestCase):
    def test_template_carries_the_script_and_units(self):
        self.assertEqual(set(FILES), {
            '/etc/ssh/sshd_config.d/10-aieh.conf', '/etc/aieh/provision.json',
            '/usr/local/sbin/aieh-provision',
            '/etc/systemd/system/aieh-provision.service', '/etc/systemd/system/aieh-provision.path',
            '/etc/systemd/system/aieh-docker-facts.service'})
        self.assertIn('  - path: /etc/aieh/provision.json\n    owner: root:root\n'
                      "    permissions: '0600'\n    encoding: b64\n"
                      '    content: "{{provision_manifest}}"\n', TEMPLATE)
        self.assertNotIn('\t', TEMPLATE)
        TEMPLATE.encode('ascii')

    def test_script_parses_and_has_no_placeholder_braces(self):
        ast.parse(SCRIPT)
        self.assertTrue(SCRIPT.startswith('#!/usr/bin/python3\n'))
        self.assertNotIn('{{', SCRIPT)
        self.assertNotIn('}}', SCRIPT)
        # nothing in the root step reaches for the network or a repository
        for word in ('apt-get update', 'curl', 'wget', 'docker pull', 'urllib', 'socket.',
                     'trusted=yes', 'allow-unauthenticated', '--force', 'sudo', 'git '):
            self.assertNotIn(word, SCRIPT)

    def test_script_paths_equal_the_profile(self):
        c = script_constants()
        self.assertEqual(c['MANIFEST'], PCONF['root_step']['manifest'])
        self.assertEqual(c['UPLOAD'], PCONF['upload']['guest_dir'])
        self.assertEqual(c['READY'], PCONF['upload']['ready_marker'])
        self.assertEqual(c['STAGING'], PCONF['root_step']['staging'])
        self.assertEqual(c['RESULT_DIR'] + '/RESULT.json', PCONF['root_step']['result'])
        self.assertEqual(c['FACTS_DIR'] + '/docker-facts.json', PCONF['facts']['path'])
        self.assertEqual(c['FACTS_UNIT'], PCONF['facts']['service'])
        self.assertEqual(c['PATH_UNIT'], PCONF['root_step']['trigger'])
        self.assertEqual(c['MANIFEST_SCHEMA'], guest.PROVISION_MANIFEST_SCHEMA)
        self.assertEqual(c['RESULT_SCHEMA'], guest.PROVISION_RESULT_SCHEMA)
        self.assertEqual(c['FACTS_SCHEMA'], guest.MOBY_FACTS_SCHEMA)
        self.assertEqual(c['ROLES'], tuple(PCONF['upload']['roles']))
        self.assertEqual(c['DAEMON_JSON'], '/etc/docker/daemon.json')
        self.assertEqual(c['MOBY_SOCKET_DIRS'], guest.MOBY_SOCKET_DIRS)

    def test_script_step_sequence_equals_the_profile(self):
        tree = ast.parse(SCRIPT)
        steps = next(n.value for n in tree.body if isinstance(n, ast.Assign)
                     and getattr(n.targets[0], 'id', None) == 'STEPS')
        names = [elt.elts[0].value for elt in steps.elts]
        self.assertEqual(names + ['facts', 'cleanup'], PCONF['root_step']['sequence'])
        # the trigger is disabled and RESULT.json is written in the finally block, last
        provision = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                         and n.name == 'provision')
        final = next(n for n in ast.walk(provision) if isinstance(n, ast.Try)).finalbody
        calls = [ast.unparse(n) for n in final]
        self.assertIn('disable_trigger()', calls[0])
        self.assertIn('write_json(RESULT, result, 420)', calls[-2])

    def test_units(self):
        service = unit('aieh-provision.service')
        path = unit('aieh-provision.path')
        facts = unit('aieh-docker-facts.service')
        for lines in (service, path):
            self.assertIn('ConditionFileNotEmpty=/etc/aieh/provision.json', lines)
            self.assertIn('ConditionPathExists=!/var/lib/aieh/provision/RESULT.json', lines)
        self.assertIn('ConditionFileNotEmpty=/etc/aieh/provision.json', facts)
        self.assertIn(f'PathExists={PCONF["upload"]["guest_dir"]}/{PCONF["upload"]["ready_marker"]}',
                      path)
        self.assertIn('Unit=aieh-provision.service', path)
        self.assertIn('Type=oneshot', service)
        self.assertIn('StandardOutput=journal+console', service)
        self.assertIn('ExecStart=/usr/bin/python3 -I /usr/local/sbin/aieh-provision provision',
                      service)
        self.assertIn('ExecStart=/usr/bin/python3 -I /usr/local/sbin/aieh-provision facts', facts)
        self.assertNotIn('[Install]', FILES['/etc/systemd/system/aieh-provision.service'])
        # the trigger is enabled by runcmd only when the manifest is not empty
        runcmd = [l for l in TEMPLATE.splitlines() if 'aieh-provision.path' in l and 'runcmd' not in l
                  and l.startswith('  - [sh')]
        self.assertEqual(len(runcmd), 1)
        self.assertIn('if [ -s /etc/aieh/provision.json ]; then', runcmd[0])

    def test_daemon_json_comes_from_the_manifest_and_has_no_tcp_socket(self):
        self.assertIn("manifest['docker']['daemon_json']", SCRIPT)
        self.assertNotIn('hosts', PCONF['moby']['daemon_json'])
        self.assertEqual(PCONF['moby']['daemon_json']['data-root'], PCONF['moby']['data_root'])


class ManifestFixture(unittest.TestCase):
    """A temporary repository with a synthetic lock, staged by provision-fetch with fakes,
    whose image archive carries crane's placeholder tag as the real one does."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-provision-b-'))
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
        self.fx = fetch_tests.Fixture()
        pdir = self.tmp / 'repo' / 'profiles' / PROFILE_NAME
        pdir.mkdir(parents=True)
        data = (json.dumps(self.fx.lock, indent=2) + '\n').encode()
        (pdir / 'provision.lock.json').write_bytes(data)
        profile = json.loads(json.dumps(PROFILE))
        profile['provider']['provision_lock'] = {
            'path': f'profiles/{PROFILE_NAME}/provision.lock.json',
            'sha256': hashlib.sha256(data).hexdigest()}
        (pdir / 'profile.json').write_text(json.dumps(profile, indent=2), encoding='utf-8')
        self.lock_sha = hashlib.sha256(data).hexdigest()
        archive = self.tagged_archive()
        guest.provision_fetch(self.ctx(), fetch_tests.FakeOpener(self.fx.urls),
                              fetch_tests.FakeCrane(self.fx, archive=archive))
        self.staged = self.state / 'provision' / self.lock_sha

    def tagged_archive(self):
        raw = self.fx.archive()
        import io
        import tarfile
        members = []
        with tarfile.open(fileobj=io.BytesIO(raw)) as tf:
            for m in tf.getmembers():
                data = tf.extractfile(m).read()
                if m.name == 'manifest.json':
                    entry = json.loads(data)
                    entry[0]['RepoTags'] = [ARCHIVE_TAG]
                    data = json.dumps(entry).encode()
                members.append((m.name, data))
        return fetch_tests.tar_bytes(members)

    def ctx(self):
        return guest.Context(str(self.tmp / 'repo' / 'profiles' / PROFILE_NAME), str(self.state))


class Manifest(ManifestFixture):
    def test_manifest_from_the_verified_stage(self):
        built = guest.build_provision_manifest(self.ctx())
        m = built['manifest']
        self.assertEqual(m['schema'], guest.PROVISION_MANIFEST_SCHEMA)
        self.assertEqual(m['lock_sha256'], self.lock_sha)
        self.assertEqual([f['role'] for f in m['files']], ['deb', 'deb', 'image-archive',
                                                          'release-binary'])
        names = [f['name'] for f in m['files']]
        self.assertEqual(names, ['tini_0.19.0-3+b8_amd64.deb',
                                 'docker.io_26.1.5+dfsg1-9+deb13u1_amd64.deb',
                                 'agent-server.tar', 'agent-server-1.60.1-linux-x86_64'])
        for f in m['files']:                         # every digest is the staged file's own
            source = built['sources'][f['name']]
            self.assertEqual((source.stat().st_size, guest.sha256_file(source)),
                             (f['size'], f['sha256']))
            self.assertTrue(guest.inside(source, self.staged))
        self.assertNotIn('InRelease', json.dumps(m))  # the index files stay on the host
        self.assertEqual(m['image']['id'], self.fx.lock['image']['config_digest'])
        self.assertEqual(m['image']['archive_repo_tags'], [ARCHIVE_TAG])
        self.assertEqual(m['image']['local_tag'], PCONF['image']['local_tag'])
        self.assertEqual(m['docker']['daemon_json'], PCONF['moby']['daemon_json'])
        self.assertEqual(built['sha256'], hashlib.sha256(built['bytes']).hexdigest())
        self.assertEqual(built['record']['manifest_sha256'], built['sha256'])
        self.assertNotIn(str(self.state).replace('\\', '/'), built['bytes'].decode())
        # deterministic, and accepted by the seed generator
        self.assertEqual(guest.build_provision_manifest(self.ctx())['bytes'], built['bytes'])
        value = nocloud_seed.provision_manifest_value(built['bytes'])
        self.assertEqual(base64.b64decode(value), built['bytes'])

    def test_a_changed_stage_is_refused(self):
        deb = self.staged / 'debs' / 'tini_0.19.0-3+b8_amd64.deb'
        deb.write_bytes(b'deb tinX')
        with self.assertRaises(guest.Refused) as caught:
            guest.build_provision_manifest(self.ctx())
        self.assertEqual(caught.exception.code, 'STAGED_MISMATCH')

    def test_no_stage_is_refused(self):
        shutil.rmtree(self.staged)
        with self.assertRaises(guest.Refused) as caught:
            guest.build_provision_manifest(self.ctx())
        self.assertIn('run provision-fetch', str(caught.exception))


class FakeGuest:
    """The guest as the provision operation sees it: SSH commands and SFTP batches act on
    a temporary directory; the READY marker runs a stand-in for the seeded root step."""

    def __init__(self, root, conf, outcome='provisioned', corrupt=None, armed='active'):
        self.root, self.conf, self.outcome, self.corrupt, self.armed = root, conf, outcome, corrupt, armed
        self.calls = []

    def path(self, guest_path):
        return self.root / guest_path.lstrip('/')

    def ssh(self, profile, idir, port):
        fake = self

        class _Ssh:
            exe = 'ssh.exe'

            def run(self, command, user='agent', input_text=None, timeout=300):
                fake.calls.append(('ssh', command, input_text))
                return fake.handle(command, input_text)
        return _Ssh()

    def sftp(self, ssh):
        fake = self

        class _Sftp:
            def batch(self, commands, work_dir, timeout=600):
                fake.calls.append(('sftp', commands))
                for command in commands:
                    verb, *args = re.findall(r'"[^"]*"|\S+', command)
                    args = [a.strip('"') for a in args]
                    if verb == 'mkdir':
                        fake.path(args[0]).mkdir(parents=True)
                    elif verb == 'put':
                        shutil.copyfile(args[0], fake.path(args[1]))
                        if fake.corrupt and args[1].endswith(fake.corrupt):
                            fake.path(args[1]).write_bytes(b'corrupted')
                    elif verb == 'get':
                        shutil.copyfile(fake.path(args[0]), args[1])
                return {'rc': 0, 'commands': commands, 'stderr': ''}
        return _Sftp()

    def completed(self, rc, out=''):
        return subprocess.CompletedProcess([], rc, out, '')

    def handle(self, command, script):
        up, root = self.conf['upload'], self.conf['root_step']
        if command == ['bash', '-s'] and 'sha256sum' in script:
            names = re.findall(r"'([^']+)'", script.split('for f in ', 1)[1].split('; do', 1)[0])
            base = self.path(up['guest_dir'])
            out = [f'{n} {(base / n).stat().st_size}' for n in names]
            out += [f'{guest.sha256_file(base / n)}  {n}' for n in names]
            return self.completed(0, '\n'.join(out) + '\n')
        if command == ['bash', '-s']:
            lines = []
            for p in re.findall(r"p='([^']+)'", script):
                lines.append(f'{"present" if self.path(p).exists() else "absent"} {p}')
            return self.completed(0, '\n'.join(lines) + '\n')
        if command[:2] == ['systemctl', 'is-active']:
            return self.completed(0, self.armed + '\n')
        if command[:2] == ['bash', '-c'] and up['ready_marker'] in command[2]:
            ready = self.path(up['guest_dir']) / up['ready_marker']
            ready.touch()
            self.root_step()
            return self.completed(0)
        if command[:2] == ['python3', '-']:
            return self.completed(0 if self.path(root['result']).exists() else 5,
                                  'result present\n')
        raise AssertionError(f'unexpected guest command {command}')

    def root_step(self):
        """What the seeded step reports: the manifest digest, every file verified, the tag."""
        m = self.manifest
        ok = self.outcome == 'provisioned'
        result = {'schema': guest.PROVISION_RESULT_SCHEMA, 'result': self.outcome,
                  'failed_step': None if ok else 'verify', 'error': None if ok else 'mismatch',
                  'manifest': {'sha256': hashlib.sha256(self.manifest_bytes).hexdigest()},
                  'steps': [{'step': 'verify', 'ok': True, 'seconds': 1.0, 'detail': {'files': [
                      dict(f, match=True) for f in m['files']]}},
                            {'step': 'tag', 'ok': True, 'seconds': 0.1, 'detail': {'image': {
                                'Id': m['image']['id'], 'RepoTags': [m['image']['local_tag']]}}},
                            {'step': 'run', 'ok': True, 'seconds': 0.5, 'detail': {'rc': 0}}]
                  if ok else [], 'trigger': {'path_unit_file': 'absent'},
                  'upload_present': not ok, 'staging_present': not ok, 'seconds': 3.0}
        target = self.path(self.conf['root_step']['result'])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result), encoding='utf-8')


class ProvisionOperation(ManifestFixture):
    def setUp(self):
        super().setUp()
        self.built = guest.build_provision_manifest(self.ctx())
        self.idir = self.state / 'instances' / 'abc'
        self.idir.mkdir(parents=True)
        self.record = {'labels': PROFILE['labels'], 'ports': {'ssh': 40001, 'qmp': 40002},
                       'provisioning': dict(self.built['record'])}
        self.guest_root = self.tmp / 'guest'
        self.guest_root.mkdir()

    def run_provision(self, record=None, **fake_kw):
        fake = FakeGuest(self.guest_root, PCONF, **fake_kw)
        fake.manifest, fake.manifest_bytes = self.built['manifest'], self.built['bytes']
        with mock.patch.object(guest, 'running_instance',
                               return_value=(self.idir, record or self.record)), \
                mock.patch.object(guest, 'Ssh', fake.ssh), \
                mock.patch.object(guest, 'Sftp', fake.sftp):
            return guest.provision(self.ctx(), 'abc'), fake

    def refused(self, code, **kw):
        with self.assertRaises(guest.Refused) as caught:
            self.run_provision(**kw)
        self.assertEqual(caught.exception.code, code, str(caught.exception))
        return caught.exception

    def test_transfer_ready_wait_and_result(self):
        result, fake = self.run_provision()
        self.assertEqual(result['result'], 'provisioned', result['checks'])
        self.assertTrue(all(result['checks'].values()))
        self.assertEqual(guest.label_problems(result['labels'], PROFILE['labels']), [])
        uploaded = sorted(p.name for p in (self.guest_root / 'srv/scratch/agent/provision').iterdir())
        self.assertEqual(uploaded, sorted([f['name'] for f in self.built['manifest']['files']] +
                                          ['READY']))
        puts = [c for c in fake.calls if c[0] == 'sftp'][0][1]
        self.assertEqual(puts[0], 'mkdir "/srv/scratch/agent/provision"')
        self.assertEqual(len(puts), 1 + len(self.built['manifest']['files']))
        order = [c[1][:2] for c in fake.calls if c[0] == 'ssh']
        self.assertEqual(order[-2:], [['bash', '-c'], ['python3', '-']])  # READY, then the wait
        fetched = Path(result['result_file'])
        self.assertTrue(guest.inside(fetched, self.idir / 'provision'))
        self.assertEqual(json.loads(fetched.read_text(encoding='utf-8'))['result'], 'provisioned')
        records = list((self.idir / 'records').glob('provision-*.json'))
        self.assertEqual(len(records), 1)
        for key in ('upload_s', 'guest_check_s', 'root_step_s', 'wait_s', 'total_s'):
            self.assertIn(key, result['timings'])

    def test_not_created_with_provision(self):
        record = dict(self.record)
        del record['provisioning']
        self.assertIn('not created with --provision', str(self.refused('REFUSED', record=record)))

    def test_stage_differs_from_the_seeded_manifest(self):
        record = dict(self.record, provisioning=dict(self.record['provisioning'],
                                                     manifest_sha256='0' * 64))
        self.refused('STAGED_MISMATCH', record=record)

    def test_single_use_and_armed_trigger(self):
        (self.guest_root / 'var/lib/aieh/provision').mkdir(parents=True)
        (self.guest_root / 'var/lib/aieh/provision/RESULT.json').write_text('{}')
        self.refused('REFUSED')
        (self.guest_root / 'var/lib/aieh/provision/RESULT.json').unlink()
        self.refused('REFUSED', armed='inactive')

    def test_bounds(self):
        small = json.loads(json.dumps(PROFILE))
        small['provisioning']['upload']['max_bytes'] = 10
        with mock.patch.object(guest, 'provisioning_config', return_value=small['provisioning']):
            self.refused('BOUNDS')

    def test_corrupted_transfer_is_caught_before_ready(self):
        error = self.refused('HASH_MISMATCH', corrupt='agent-server.tar')
        self.assertEqual(error.detail['guest_check']['mismatched'], ['agent-server.tar'])
        self.assertFalse((self.guest_root / 'srv/scratch/agent/provision/READY').exists())

    def test_failed_root_step_is_reported_and_recorded(self):
        error = self.refused('PROVISION_FAILED', outcome='failed')
        self.assertIn("step 'verify'", str(error))
        self.assertEqual(error.detail['result'], 'failed')
        self.assertEqual(len(list((self.idir / 'records').glob('provision-*.json'))), 1)


class SmokeAndCli(unittest.TestCase):
    def test_smoke_runs_provision_after_create_and_recreate(self):
        src = (REPO / 'tools' / 'guest.py').read_text(encoding='utf-8')
        body = src[src.index('def smoke('):src.index('# ---------------------------------------------------------------- netprobe')]
        self.assertIn("run('provision', lambda: provision(ctx, name), provisioned)", body)
        self.assertIn("run('provision (after recreate)', lambda: provision(ctx, name), provisioned)",
                      body)
        self.assertLess(body.index("run('provision',"), body.index("do_inspect('A (after create)')"))
        self.assertLess(body.index("'provision (after recreate)'"),
                        body.index("do_inspect('C (after recreate)')"))

    def test_cli(self):
        tmp = Path(tempfile.mkdtemp(prefix='aieh-provision-cli-'))
        self.addCleanup(shutil.rmtree, tmp, True)
        state = tmp / 'state'
        state.mkdir()
        env = {'USERPROFILE': str(tmp / 'h'), 'HOME': str(tmp / 'h')}
        base = ['--profile', str(PROFILE_DIR), '--state-dir', str(state), '--name', 'abc']
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(guest, 'create', return_value={'operation': 'create',
                                                                 'result': 'ready'}) as create, \
                mock.patch.object(guest, 'provision', return_value={'operation': 'provision',
                                                                    'result': 'provisioned'}) as prov, \
                mock.patch.object(guest, 'smoke', return_value={'operation': 'smoke',
                                                                'result': 'PASS'}) as smoke:
            self.assertEqual(guest.main(['create'] + base + ['--provision']), 0)
            self.assertIs(create.call_args.kwargs.get('provision'), True)
            self.assertEqual(guest.main(['create'] + base), 0)
            self.assertNotIn('provision', create.call_args.kwargs)
            self.assertEqual(guest.main(['provision'] + base), 0)
            self.assertEqual(prov.call_args.args[1], 'abc')
            self.assertEqual(guest.main(['smoke'] + base + ['--canaries', 'C', '--durable', 'D',
                                                            '--provision']), 0)
            self.assertIs(smoke.call_args.args[6], True)

    def test_validation_instances_are_never_provisioned(self):
        with self.assertRaises(guest.Refused):
            guest.create(None, 'abc', netprobe=object(), provision=True)


if __name__ == '__main__':
    unittest.main()
