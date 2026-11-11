"""Tests for D-6 of plan leaf S-03.3 (the slice plan section 6; the Overseer's ruling on the S-03.3 row): the job
contract's admission of the broker attempt token's environment name (tools/guest.py attempt_token_environment,
attempt_token_spec, attempt_token_admission, job_env_verdict and JOB_ENV_PROBE's shape report).

Run from the repository root:  python -I -B -m unittest discover -s tools/tests -v

stdlib unittest; no guest. Shown: the name is admitted only for a guest created with the inference composition and
only where the probe reports a token-shaped value that has no provider key's shape; without the names the old
contract holds exactly; the probe itself, run over an in-memory /proc, reports shapes and never a value.
"""
from pathlib import Path
import base64
import builtins
import contextlib
import copy
import io
import json
import subprocess
import sys
import unittest
from unittest import mock

CATEGORY = 'unit'

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import module_code  # noqa: E402
guest = module_code.load('guest', REPO / 'tools' / 'guest.py')
PROFILE = json.loads((REPO / 'profiles' / 'strong-windows-qemu-whpx' / 'profile.json').read_text(encoding='utf-8'))
RECORD = {'provisioning': {'image_id': 'x'}, 'ports': {'ssh': 40022, 'qmp': 40023},
          'inference': {'composition': 'inference'}}
SERVER_USER = {'name': 'openhands', 'uid': 999, 'gid': 989}
TOKEN = 'aieh-inf-' + 'T' * 43
REAL = 'sk-ant-api03-' + 'R' * 40


def job_env(shapes=None, names=('ANTHROPIC_API_KEY',)):
    """A job environment probe's answer: the server user, confined; the adapter (pid 20) holds the token's name."""
    st = {'Uid': '999 999 999 999', 'Gid': '989 989 989 989', 'Groups': '989', 'CapInh': '0' * 16,
          'CapPrm': '0' * 16, 'CapEff': '0' * 16, 'CapBnd': '0' * 16, 'CapAmb': '0' * 16, 'NoNewPrivs': '1',
          'Seccomp': '2'}
    envs = {'1': {'comm': 'tini', 'names': ['OH_SECRET_KEY', 'OH_SESSION_API_KEYS_0']},
            '20': {'comm': 'node', 'names': sorted(['OH_SECRET_KEY', 'OH_SESSION_API_KEYS_0', *names])}}
    if shapes is not None:
        envs['20']['shapes'] = shapes
    return {'id': 'uid=999 gid=989', 'self': st, 'pid1': st, 'apparmor': 'docker-default (enforce)',
            'process_environments': envs, 'terminal_names': [], 'socket_files': [], 'setuid_root': [],
            'unix_bound': [], 'connect': {}, 'sudo': None, 'su': None}


TOKEN_SHAPED = {'ANTHROPIC_API_KEY': {'token': True, 'provider_key': False}}


class AttemptTokenContract(unittest.TestCase):
    """D-6: the attempt token's environment name in the job contract, gated under the inference composition."""

    def test_the_name_is_admitted_only_for_an_opted_in_guest(self):
        self.assertEqual(guest.attempt_token_environment(PROFILE, RECORD), ('ANTHROPIC_API_KEY',))
        self.assertEqual(guest.attempt_token_environment(PROFILE, {'provisioning': {}}), ())
        self.assertEqual(guest.attempt_token_environment(PROFILE, {'inference': {'composition': 'other'}}), ())
        bare = copy.deepcopy(PROFILE)
        del bare['network']['inference_composition']['attempt_token_environment']
        self.assertEqual(guest.attempt_token_environment(bare, RECORD), ())
        for names in ('ANTHROPIC_API_KEY', [''], [1], None):
            bare['network']['inference_composition']['attempt_token_environment'] = {'names': names}
            self.assertEqual(guest.attempt_token_environment(bare, RECORD), ())

    def test_the_verdict_admits_only_token_shapes(self):
        names = ('ANTHROPIC_API_KEY',)
        ok, problems, root = guest.job_env_verdict(PROFILE, SERVER_USER, job_env(TOKEN_SHAPED), names)
        self.assertEqual((ok, problems, root), (True, [], False))
        for shapes in ({'ANTHROPIC_API_KEY': {'token': False, 'provider_key': False}},
                       {'ANTHROPIC_API_KEY': {'token': True, 'provider_key': True}},
                       {'ANTHROPIC_API_KEY': {'token': True}}, {}, None):
            with self.subTest(shapes=shapes):
                ok, problems, _ = guest.job_env_verdict(PROFILE, SERVER_USER, job_env(shapes), names)
                self.assertFalse(ok)
                self.assertEqual(problems[0]['check'], 'process environments: only the conversation keys')
                self.assertEqual(problems[0]['observed'], {'20': sorted(['ANTHROPIC_API_KEY', 'OH_SECRET_KEY',
                                                                         'OH_SESSION_API_KEYS_0'])})

    def test_without_the_names_the_old_contract_holds_exactly(self):
        for data in (job_env(TOKEN_SHAPED), job_env()):
            ok, problems, _ = guest.job_env_verdict(PROFILE, SERVER_USER, data)
            self.assertFalse(ok)
            self.assertEqual(problems, [{'check': 'process environments: only the conversation keys',
                                         'observed': {'20': sorted(['ANTHROPIC_API_KEY', 'OH_SECRET_KEY',
                                                                    'OH_SESSION_API_KEYS_0'])}}])
        ok, problems, _ = guest.job_env_verdict(PROFILE, SERVER_USER, job_env(names=()))
        self.assertEqual((ok, problems), (True, []))
        # another credential-like name is never admitted by the token's names
        data = job_env(dict(TOKEN_SHAPED, GITEA_TOKEN={'token': True, 'provider_key': False}),
                       names=('ANTHROPIC_API_KEY', 'GITEA_TOKEN'))
        ok, problems, _ = guest.job_env_verdict(PROFILE, SERVER_USER, data, ('ANTHROPIC_API_KEY',))
        self.assertFalse(ok)

    def test_admission_classifies_by_shape(self):
        data = job_env({'ANTHROPIC_API_KEY': {'token': True, 'provider_key': False}})
        data['process_environments']['21'] = {'names': ['ANTHROPIC_API_KEY'],
                                              'shapes': {'ANTHROPIC_API_KEY': {'token': False, 'provider_key': True}}}
        data['process_environments']['22'] = {'names': ['ANTHROPIC_API_KEY'],
                                              'shapes': {'ANTHROPIC_API_KEY': {'token': False, 'provider_key': False}}}
        data['process_environments']['23'] = {'names': ['ANTHROPIC_API_KEY']}
        self.assertEqual(guest.attempt_token_admission(data, ('ANTHROPIC_API_KEY',)), {
            'admitted': {'20': ['ANTHROPIC_API_KEY']}, 'provider_key': {'21': ['ANTHROPIC_API_KEY']},
            'not_token': {'22': ['ANTHROPIC_API_KEY'], '23': ['ANTHROPIC_API_KEY']}})
        self.assertEqual(guest.attempt_token_admission(data, ()), {'admitted': {}, 'not_token': {},
                                                                   'provider_key': {}})

    def test_the_spec_takes_the_shapes_from_their_sources(self):
        acp = guest.acp_qualification()
        spec = guest.attempt_token_spec(('ANTHROPIC_API_KEY',))
        self.assertEqual(spec, {'names': ['ANTHROPIC_API_KEY'], 'token_shape': acp.broker.TOKEN_SHAPE.pattern,
                                'provider_key_shape': acp.PROVIDER_KEY_SHAPE.pattern})
        block = PROFILE['network']['inference_composition']['attempt_token_environment']
        self.assertEqual((block['value_shape'], block['refused_shapes']),
                         (spec['token_shape'], spec['provider_key_shape']))

    def test_the_probe_reports_shapes_never_values(self):
        """JOB_ENV_PROBE itself, over an in-memory /proc: the shapes of the admitted name's value only."""
        out = run_env_probe({'1': b'OH_SECRET_KEY=x\0OH_SESSION_API_KEYS_0=y\0PATH=/bin\0',
                             '20': b'ANTHROPIC_API_KEY=' + TOKEN.encode() + b'\0ANTHROPIC_BASE_URL=http://a\0',
                             '21': b'ANTHROPIC_API_KEY=' + REAL.encode() + b'\0',
                             '22': b'ANTHROPIC_API_KEY=' + TOKEN.encode() + b'x\0OTHER=1\0',
                             '23': b'ANTHROPIC_API_KEYS=' + TOKEN.encode() + b'\0',
                             '24': b'ANTHROPIC_API_KEY\0'},
                            guest.attempt_token_spec(('ANTHROPIC_API_KEY',)))
        envs = out['process_environments']
        self.assertEqual(envs['20']['shapes'], {'ANTHROPIC_API_KEY': {'token': True, 'provider_key': False}})
        self.assertEqual(envs['21']['shapes'], {'ANTHROPIC_API_KEY': {'token': False, 'provider_key': True}})
        self.assertEqual(envs['22']['shapes'], {'ANTHROPIC_API_KEY': {'token': False, 'provider_key': False}})
        self.assertNotIn('shapes', envs['1'])
        self.assertNotIn('shapes', envs['23'])
        self.assertEqual(envs['24'], {'comm': 'c24', 'names': ['ANTHROPIC_API_KEY']})   # a name without '='
        self.assertEqual(envs['20']['names'], ['ANTHROPIC_API_KEY'])
        text = json.dumps(out)
        self.assertNotIn(TOKEN, text)
        self.assertNotIn(REAL, text)
        # without the entry the probe's answer is the old one
        old = run_env_probe({'20': b'ANTHROPIC_API_KEY=' + TOKEN.encode() + b'\0'}, None)
        self.assertEqual(old['process_environments']['20'], {'comm': 'c20', 'names': ['ANTHROPIC_API_KEY']})


def run_env_probe(environs, token_spec):
    """Run guest.JOB_ENV_PROBE over an in-memory /proc (environ and comm per pid), no walk, no socket, no process."""
    spec = {'pattern': PROFILE['provisioning']['agent_server']['jobs']['environment']['credential_name_pattern'],
            'sockets': [], 'timeout': 1}
    if token_spec is not None:
        spec['attempt_token'] = token_spec
    files = {f'/proc/{pid}/environ': data for pid, data in environs.items()}
    files.update({f'/proc/{pid}/comm': f'c{pid}\n'.encode() for pid in environs})
    files.update({'/proc/self/status': b'Uid:\t1\n', '/proc/1/status': b'Uid:\t1\n',
                  '/proc/self/attr/current': b'x\n', '/proc/net/unix': b'header\n'})
    real_open = builtins.open

    def fake_open(path, mode='r', *args, **kwargs):
        if isinstance(path, str) and path.startswith('/proc'):
            if path not in files:
                raise FileNotFoundError(path)
            data = files[path]
            return io.BytesIO(data) if 'b' in mode else io.StringIO(data.decode())
        return real_open(path, mode, *args, **kwargs)
    printed = io.StringIO()
    argv = ['probe', base64.b64encode(json.dumps(spec).encode()).decode()]
    with mock.patch('builtins.open', fake_open), mock.patch('os.listdir', return_value=sorted(environs)), \
            mock.patch('os.walk', return_value=iter(())), mock.patch('shutil.which', return_value=None), \
            mock.patch('subprocess.run', return_value=subprocess.CompletedProcess([], 0, 'uid=1', '')), \
            mock.patch.object(sys, 'argv', argv), contextlib.redirect_stdout(printed):
        exec(compile(guest.JOB_ENV_PROBE, 'JOB_ENV_PROBE', 'exec'), {'__name__': '__probe__'})
    line = [x for x in printed.getvalue().splitlines() if x.startswith(guest.JOB_MARKER)][-1]
    return json.loads(line[len(guest.JOB_MARKER):])

if __name__ == '__main__':
    unittest.main()
