"""Tests for tools/check_ci_policy.py, policy/ci-runner-profile.json, policy/ci-token-secret-policy.json
and policy/ci/workflows/ (plan leaf Q-02.1).

Run from the repository root:  python -I -B -m unittest discover -s tools/tests -v

The committed profile, policy and workflow must pass against the committed inventory, network
matrix, role-token matrix, lock, profiles and README. Each negative case mutates an in-memory
copy (of the profile, the policy, a workflow's text or a profile variant) and must fail with
the expected code. The inputs are loaded once; no test reads the bootstrap log (the one case
that needs it is given a synthetic log), and the checkout is only read.
"""
from pathlib import Path
import contextlib
import copy
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest

CATEGORY = 'unit'

REPO = Path(__file__).resolve().parents[2]
CHECKER = REPO / 'tools' / 'check_ci_policy.py'
PROFILE_PATH = REPO / 'policy' / 'ci-runner-profile.json'
POLICY_PATH = REPO / 'policy' / 'ci-token-secret-policy.json'
README_PATH = REPO / 'policy' / 'README.md'
WORKFLOW_REL = 'policy/ci/workflows/validation.yml'

_spec = importlib.util.spec_from_file_location('check_ci_policy', CHECKER)
ccp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ccp)

PROFILE_TEXT = PROFILE_PATH.read_text(encoding='utf-8')
POLICY_TEXT = POLICY_PATH.read_text(encoding='utf-8')
PROFILE = json.loads(PROFILE_TEXT)
POLICY = json.loads(POLICY_TEXT)
README = README_PATH.read_text(encoding='utf-8')
WORKFLOW = (REPO / WORKFLOW_REL).read_text(encoding='utf-8')
INPUTS = ccp.load_inputs(REPO, PROFILE)

# An act_runner config.yaml (as JSON) that satisfies every invariant, for the variant cases.
DIGEST = 'a' * 64
GOOD_CONFIG = {
    'runner': {'labels': [f'aieh-validation:docker://registry.example/job@sha256:{DIGEST}'],
               'envs': {}, 'env_file': '', 'capacity': 1, 'timeout': '1h',
               'tool_cache_mode': 'none', 'hooks': {}, 'post_task_script': '',
               'extra_headers': {}},
    'cache': {'enabled': False},
    'container': {'privileged': False, 'docker_host': '-', 'valid_volumes': [], 'network': '',
                  'network_create_options': {'enable_ipv6': False}, 'force_pull': False,
                  'force_rebuild': False, 'bind_workdir': False, 'sweep': False,
                  'options': ' '.join(PROFILE['runner_config']['options']['declared'])},
    'metrics': {'enabled': False},
    'health_check': {'enabled': False},
}
CONFIG_PATH = '/etc/aieh/ci-runner/config.yaml'
# The variant's runner service and register call (rulings (3) and (5) of 2026-11-12).
GOOD_SERVICE = {'environment': {'HOME': '/var/lib/aieh-ci-runner', 'PATH': '/usr/bin:/bin'},
                'argv': ['/opt/aieh/ci-runner/gitea-runner', 'daemon', '--config', CONFIG_PATH]}
GOOD_REGISTER = {'argv': ['/opt/aieh/ci-runner/gitea-runner', 'register', '--no-interactive',
                          '--config', CONFIG_PATH, '--instance', 'http://127.0.0.1:13300',
                          '--token-file', '/run/aieh/ci-runner/registration-token',
                          '--name', 'aieh-ci']}


def fresh():
    """New parses of the committed profile and policy, sharing nothing with any other copy."""
    return json.loads(PROFILE_TEXT), json.loads(POLICY_TEXT)


def item(rows, key, value):
    for row in rows:
        if row.get(key) == value:
            return row
    raise AssertionError(f'fixture has no row {key}={value!r}')


def variant(config, service=None, register=None):
    """A profile variant declaring CONFIG, with the good service and register call unless given
    (a value of False leaves that block out)."""
    block = {'config': config,
             'service': copy.deepcopy(GOOD_SERVICE) if service is None else service,
             'register': copy.deepcopy(GOOD_REGISTER) if register is None else register}
    return {'ci-variant': {'provisioning': {'ci_runner': {k: v for k, v in block.items()
                                                         if v is not False}}}}


def run_cli(*args):
    return subprocess.run([sys.executable, '-I', '-B', str(CHECKER), *map(str, args)],
                          capture_output=True, text=True, encoding='utf-8', cwd=REPO)


class FakeFiles:
    """The shared repository files, with a synthetic bootstrap log."""

    def __init__(self, files, log):
        self.files, self.log = files, log

    def read_text(self, rel):
        return self.log if rel == ccp.BOOTSTRAP_LOG else self.files.read_text(rel)

    def is_file(self, rel):
        return True if str(rel) == ccp.BOOTSTRAP_LOG else self.files.is_file(rel)

    def plan_ids(self):
        return self.files.plan_ids()


class Base(unittest.TestCase):

    def codes(self, profile=None, policy=None, readme=README, workflows=None, profiles=None,
              inputs=None):
        p, q = fresh()
        problems = ccp.evaluate(p if profile is None else profile, q if policy is None else policy,
                                INPUTS if inputs is None else inputs, readme, workflows, profiles)
        return {x.code for x in problems}, problems

    def assert_code(self, code, where=None, **kwargs):
        found, problems = self.codes(**kwargs)
        self.assertIn(code, found, '\n'.join(map(str, problems)))
        if where:
            self.assertTrue(any(x.code == code and where in x.where for x in problems),
                            '\n'.join(map(str, problems)))
        return problems

    def assert_workflow(self, code, old, new, count=1):
        self.assertEqual(WORKFLOW.count(old), count, old)
        self.assert_code(code, workflows={WORKFLOW_REL: WORKFLOW.replace(old, new)})


class CommittedPolicy(Base):
    category = 'contract'

    def test_committed_policy_passes(self):
        problems = ccp.check(json.loads(PROFILE_TEXT), json.loads(POLICY_TEXT), REPO, README)
        self.assertEqual(problems, [], '\n'.join(map(str, problems)))

    def test_no_validation_lane_reaches_a_privileged_credential(self):
        """The leaf's acceptance, read straight from the data, independently of the checker."""
        authority = {c['id']: c['authority'] for c in INPUTS.inventory['credentials']}
        lanes = {r['credential']: r['lane'] for r in POLICY['credential_lanes']}
        self.assertEqual(set(lanes), set(authority))
        job = sorted(c for c, lane in lanes.items() if lane == 'validation-job')
        runner = sorted(c for c, lane in lanes.items() if lane == 'validation-runner-host')
        self.assertEqual(job, ['cred-ci-job-token', 'cred-ci-runtime-token'])
        self.assertEqual(runner, ['cred-runner-token'])
        for cid in job + runner:
            self.assertEqual(authority[cid], 'scoped', cid)
        for row in POLICY['task_tokens']:
            self.assertEqual((row['reach'], row['relied_on']), ('none', False))
        self.assertEqual(item(PROFILE['lanes'], 'id', 'validation-job')['reaches'], [])
        for row in PROFILE['reach']:
            if row['from'] == 'td-untrusted-ci':
                self.assertEqual((row['kind'], row['credentials']), ('none', []))
        for key in ccp.SECRET_SETS:
            self.assertEqual(PROFILE['gitea']['secrets'][key], [])

    def test_every_forward_is_an_owner_act(self):
        acts = {a['id']: a for a in PROFILE['owner_acts']}
        forwards = [r for r in PROFILE['reach'] if r['kind'] in ('forward', 'listener')]
        self.assertTrue(forwards)
        for row in forwards + [PROFILE['endpoint'], PROFILE['proxy']]:
            self.assertIn(row['owner_act'], acts)
            self.assertEqual(acts[row['owner_act']]['status'], 'planned')
        runner_gitea = item(PROFILE['reach'], 'id', 'ci-r1')
        self.assertEqual((runner_gitea['from'], runner_gitea['class'], runner_gitea['owner_act']),
                         ('td-ci-runner-host', 'ci-control', 'A-1'))

    def test_the_job_token_is_permissionless_under_the_ceiling(self):
        token = item(POLICY['task_tokens'], 'credential', 'cred-ci-job-token')
        self.assertEqual(token['effective_permission']['governance_repository'], 'none')
        for row in POLICY['ceilings']['owners'] + POLICY['ceilings']['repositories']:
            self.assertEqual(row['token_permission_mode'], 'restricted')
            self.assertEqual(set(row['max_token_permissions'].values()), {'none'})
        doc = ccp.parse_yaml_subset(WORKFLOW)
        self.assertEqual(doc['permissions'], {})
        self.assertEqual(list(doc['on']), ['workflow_dispatch'])

    def test_facts_are_verified_at_source_never_live(self):
        for fact in POLICY['gitea_facts']:
            if fact['id'] == 'A1':
                self.assertIs(fact['verified'], False)
            else:
                self.assertEqual(fact['verified'], 'source', fact['id'])
        self.assertEqual([f['id'] for f in POLICY['gitea_facts']],
                         [f'G{n}' for n in range(1, 11)] + ['A1'])

    def test_cli_passes_and_lists(self):
        result = run_cli('--list')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS policy/ci-runner-profile.json', result.stdout)
        self.assertIn('owner act A-1: requested at Q-02.2.2 (planned)', result.stdout)

    def test_cli_render_matches_the_readme(self):
        result = run_cli('--render')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(ccp.generated_block(README).strip(), result.stdout.strip())


class CommandLine(Base):
    """The command line in process: FAIL, could-not-run and the live-report interface."""

    def main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = ccp.main([*map(str, argv)])
        return code, out.getvalue(), err.getvalue()

    def test_a_mutated_copy_fails(self):
        p, _ = fresh()
        item(p['lanes'], 'id', 'validation-job')['holds'].append('cred-gitea-admin')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'ci-runner-profile.json'
            path.write_text(json.dumps(p), encoding='utf-8')
            code, out, _ = self.main('--root', REPO, '--profile', path)
            readme = Path(tmp) / 'README.md'
            readme.write_text(README.replace(ccp.GENERATED_BEGIN, ''), encoding='utf-8')
            stale_code, stale_out, _ = self.main('--root', REPO, '--readme', readme)
        self.assertEqual(code, 1, out)
        self.assertIn('FAIL LANE_PRIVILEGED', out)
        self.assertEqual(stale_code, 1, stale_out)
        self.assertIn('FAIL README_STALE', stale_out)

    def test_it_cannot_run_without_a_profile(self):
        code, _, err = self.main('--root', REPO, '--profile', REPO / 'policy' / 'no-such-profile.json')
        self.assertEqual(code, 2)
        self.assertIn('cannot read', err)

    def test_the_live_report_is_an_interface_only(self):
        code, out, err = self.main('--root', REPO, '--live-report', 'report.json')
        self.assertEqual(code, 2)
        self.assertIn('interface only', err)
        self.assertEqual(out, '')

    def test_the_committed_files_pass_in_process(self):
        code, out, _ = self.main('--root', REPO)
        self.assertEqual(code, 0, out)
        self.assertIn('PASS', out)


class Lanes(Base):

    def test_a_privileged_credential_in_a_validation_lane_fails(self):
        p, q = fresh()
        item(p['lanes'], 'id', 'validation-job')['holds'].append('cred-gitea-admin')
        self.assert_code('LANE_PRIVILEGED', 'lanes.validation-job', profile=p)
        p, q = fresh()
        item(q['credential_lanes'], 'credential', 'cred-guest-ssh-key')['lane'] = \
            'validation-runner-host'
        self.assert_code('LANE_PRIVILEGED', 'cred-guest-ssh-key', policy=q)

    def test_the_job_holds_exactly_the_two_task_tokens(self):
        _, q = fresh()
        item(q['credential_lanes'], 'credential', 'cred-ci-runtime-token')['lane'] = 'trusted-lane'
        self.assert_code('LANE_JOB_CREDENTIALS', policy=q)

    def test_the_runner_host_holds_exactly_the_runner_token(self):
        _, q = fresh()
        item(q['credential_lanes'], 'credential', 'cred-runner-token')['lane'] = 'trusted-lane'
        self.assert_code('LANE_RUNNER_CREDENTIALS', policy=q)

    def test_the_profile_lanes_equal_the_map(self):
        p, _ = fresh()
        item(p['lanes'], 'id', 'validation-runner-host')['holds'] = []
        self.assert_code('LANE_HOLDS_MISMATCH', 'validation-runner-host', profile=p)

    def test_every_credential_has_a_lane(self):
        _, q = fresh()
        q['credential_lanes'] = [r for r in q['credential_lanes']
                                 if r['credential'] != 'cred-llm-provider-key']
        self.assert_code('LANE_MAP_INCOMPLETE', 'cred-llm-provider-key', policy=q)

    def test_a_ci_held_credential_is_in_its_domain_lane(self):
        _, q = fresh()
        item(q['credential_lanes'], 'credential', 'cred-ci-job-token')['lane'] = 'none'
        self.assert_code('LANE_MAP_MISMATCH', 'cred-ci-job-token', policy=q)
        _, q = fresh()
        item(q['credential_lanes'], 'credential', 'cred-verifier-read')['lane'] = 'validation-job'
        self.assert_code('LANE_MAP_MISMATCH', 'cred-verifier-read', policy=q)

    def test_the_job_reaches_nothing(self):
        p, _ = fresh()
        item(p['lanes'], 'id', 'validation-job')['reaches'] = ['ci-r1']
        self.assert_code('JOB_REACH', 'lanes.validation-job', profile=p)
        p, _ = fresh()
        row = item(p['reach'], 'id', 'ci-r2')
        row['kind'], row['to'] = 'existing', 'gitea-server'
        self.assert_code('JOB_REACH', 'reach.ci-r2', profile=p)
        for key, value in (('reach', 'gitea'), ('relied_on', True)):
            _, q = fresh()
            item(q['task_tokens'], 'credential', 'cred-ci-job-token')[key] = value
            self.assert_code('JOB_REACH', 'cred-ci-job-token', policy=q)

    def test_task_token_rows(self):
        _, q = fresh()
        item(q['task_tokens'], 'credential', 'cred-ci-job-token')['effective_permission'][
            'governance_repository'] = 'read'
        self.assert_code('TOKEN_ROW', 'cred-ci-job-token', policy=q)
        _, q = fresh()
        item(q['task_tokens'], 'credential', 'cred-ci-runtime-token')['holder'] = 'ci-runner-service'
        self.assert_code('TOKEN_ROW', 'cred-ci-runtime-token', policy=q)
        _, q = fresh()
        q['task_tokens'].pop()
        self.assert_code('TOKEN_ROW', 'task_tokens', policy=q)


class RunnerConfig(Base):

    def test_a_missing_invariant_fails(self):
        p, _ = fresh()
        p['runner_config']['rules'] = [r for r in p['runner_config']['rules']
                                       if r['path'] != 'container.docker_host']
        self.assert_code('RUNNER_RULE_MISSING', 'container.docker_host', profile=p)

    def test_a_weakened_invariant_fails(self):
        for path, value in (('cache.enabled', True), ('container.privileged', 0),
                            ('runner.capacity', 2), ('container.docker_host', '')):
            p, _ = fresh()
            item(p['runner_config']['rules'], 'path', path)['value'] = value
            self.assert_code('RUNNER_RULE_WEAK', path, profile=p)
        p, _ = fresh()
        item(p['runner_config']['rules'], 'path', 'runner.envs')['rule'] = 'must_be_set'
        self.assert_code('RUNNER_RULE_WEAK', 'runner.envs', profile=p)
        p, _ = fresh()
        p['runner_config']['label']['name'] = 'host'
        self.assert_code('RUNNER_RULE_WEAK', 'runner_config.label', profile=p)

    def test_weakened_declared_options_fail(self):
        declared = PROFILE['runner_config']['options']['declared']
        cases = [declared + ['--privileged'], declared + ['--cap-add=SYS_ADMIN'],
                 declared + ['--volume=/:/host'], [o for o in declared if o != '--cap-drop=ALL'],
                 [o for o in declared if not o.startswith('--memory=')],
                 [o if not o.startswith('--user=') else '--user=0:0' for o in declared],
                 declared + ['--security-opt=seccomp=unconfined']]
        for options in cases:
            p, _ = fresh()
            p['runner_config']['options']['declared'] = options
            self.assert_code('RUNNER_RULE_WEAK', 'runner_config.options', profile=p)
        p, _ = fresh()
        p['runner_config']['options']['exchange_mount'] = '--volume=/home/agent/exchange:/aieh/exchange'
        self.assert_code('RUNNER_RULE_WEAK', 'runner_config.options', profile=p)

    def test_a_good_variant_config_passes(self):
        found, problems = self.codes(profiles=variant(copy.deepcopy(GOOD_CONFIG)))
        self.assertEqual(problems, [], '\n'.join(map(str, problems)))

    def test_variant_config_violations_fail(self):
        mutations = [
            ('runner', 'labels', ['host']),
            ('runner', 'labels', ['aieh-validation:lxc://debian']),
            ('runner', 'labels', [f'aieh-validation:docker://job@sha256:{DIGEST}', 'ubuntu:host']),
            ('runner', 'labels', ['aieh-validation:docker://job:latest']),
            ('runner', 'envs', {'TOKEN': 'x'}),
            ('runner', 'env_file', '.env'),
            ('runner', 'capacity', 4),
            ('runner', 'timeout', ''),
            ('cache', 'enabled', True),
            ('container', 'privileged', True),
            ('container', 'docker_host', ''),
            ('container', 'docker_host', 'unix:///var/run/docker.sock'),
            ('container', 'valid_volumes', ['/']),
            ('container', 'network', 'host'),
            ('container', 'enable_ipv6', True),
            ('container', 'force_pull', True),
            ('container', 'force_rebuild', True),
            # the keys of the 6.0.0 pin (rulings (2) and (3) of 2026-11-12)
            ('container', 'enable_ipv6', False),
            ('container', 'network_create_options', {'enable_ipv6': True}),
            ('container', 'network_create_options', {}),
            ('container', 'bind_workdir', True),
            ('container', 'bind_workdir', 0),
            ('container', 'sweep', True),
            ('runner', 'tool_cache_mode', 'shared'),
            ('runner', 'tool_cache_mode', ''),
            ('runner', 'hooks', {'job_started': '/hooks/started.sh'}),
            ('runner', 'hooks', {'job_completed': ''}),
            ('runner', 'post_task_script', '/usr/local/bin/after.sh'),
            ('runner', 'extra_headers', {'X-Extra': 'value'}),
            ('metrics', 'enabled', True),
            ('health_check', 'enabled', True),
        ]
        for section, key, value in mutations:
            config = copy.deepcopy(GOOD_CONFIG)
            config[section][key] = value
            self.assert_code('RUNNER_CONFIG', 'profiles/ci-variant', profiles=variant(config))
        for section, key in (('container', 'network_create_options'), ('container', 'bind_workdir'),
                             ('container', 'sweep'), ('runner', 'tool_cache_mode'),
                             ('metrics', 'enabled'), ('health_check', 'enabled')):
            config = copy.deepcopy(GOOD_CONFIG)
            del config[section][key]
            self.assert_code('RUNNER_CONFIG', 'profiles/ci-variant', profiles=variant(config))
        for section in ('metrics', 'health_check'):
            config = copy.deepcopy(GOOD_CONFIG)
            del config[section]
            self.assert_code('RUNNER_CONFIG', 'profiles/ci-variant', profiles=variant(config))

    def test_variant_config_holds_no_environment_expansion(self):
        # The runner replaces ${NAME} in config.yaml values from its environment at load.
        for section, key, value in (('runner', 'timeout', '${TIMEOUT}'),
                                    ('container', 'network', '$NETWORK'),
                                    ('runner', 'labels', [f'aieh-validation:docker://${{IMAGE}}'
                                                          f'@sha256:{DIGEST}'])):
            config = copy.deepcopy(GOOD_CONFIG)
            config[section][key] = value
            problems = self.assert_code('RUNNER_CONFIG', 'profiles/ci-variant',
                                        profiles=variant(config))
            self.assertTrue(any('holds $' in x.message for x in problems))
        config = copy.deepcopy(GOOD_CONFIG)
        config['runner']['envs'] = {'${KEY}': ''}
        problems = self.assert_code('RUNNER_CONFIG', 'profiles/ci-variant', profiles=variant(config))
        self.assertTrue(any('holds $' in x.message for x in problems))

    def test_the_policy_declares_the_6_0_0_keys(self):
        p, _ = fresh()
        item(p['runner_config']['rules'], 'path',
             'container.network_create_options.enable_ipv6')['value'] = True
        self.assert_code('RUNNER_RULE_WEAK', 'network_create_options.enable_ipv6', profile=p)
        p, _ = fresh()
        stale = item(p['runner_config']['rules'], 'path', 'container.enable_ipv6')
        stale['rule'], stale['value'] = 'must_equal', False
        self.assert_code('RUNNER_RULE_WEAK', 'container.enable_ipv6', profile=p)
        for path in ('container.bind_workdir', 'container.sweep', 'runner.tool_cache_mode',
                     'runner.hooks', 'runner.post_task_script', 'runner.extra_headers',
                     'metrics.enabled', 'health_check.enabled'):
            p, _ = fresh()
            p['runner_config']['rules'] = [r for r in p['runner_config']['rules'] if r['path'] != path]
            self.assert_code('RUNNER_RULE_MISSING', path, profile=p)
        p, _ = fresh()
        item(p['runner_config']['rules'], 'path', 'runner.tool_cache_mode')['value'] = 'shared'
        self.assert_code('RUNNER_RULE_WEAK', 'runner.tool_cache_mode', profile=p)

    def test_variant_options_outside_the_declared_list_fail(self):
        for extra in ('--privileged', '--cap-add=NET_ADMIN', '--device=/dev/kvm', '--pid=host',
                      '--network=host', '--userns=host', '--security-opt=apparmor=unconfined',
                      '-v /var/run/docker.sock:/var/run/docker.sock', '--volume=/home:/home',
                      '--mount=type=bind,src=/,dst=/host', '--tmpfs=/x'):
            config = copy.deepcopy(GOOD_CONFIG)
            config['container']['options'] += ' ' + extra
            self.assert_code('RUNNER_CONFIG', 'profiles/ci-variant', profiles=variant(config))
        config = copy.deepcopy(GOOD_CONFIG)
        config['container']['options'] = '--cap-drop=ALL'
        self.assert_code('RUNNER_CONFIG', 'profiles/ci-variant', profiles=variant(config))

    def test_the_variant_key_is_declared(self):
        p, _ = fresh()
        p['runner_config']['profile_key'] = ''
        self.assert_code('SCHEMA', 'runner_config.profile_key', profile=p)


class RunnerServiceAndRegistration(Base):
    """The runner's environment (ruling (3)) and the registration token's input (ruling (5)),
    2026-11-12, in the policy and in a variant's declared service and register call."""

    def assert_clean(self, **kwargs):
        found, problems = self.codes(**kwargs)
        self.assertEqual(problems, [], '\n'.join(map(str, problems)))

    def test_the_good_service_and_register_call_pass_in_either_spelling(self):
        register = copy.deepcopy(GOOD_REGISTER)
        register['argv'] = [a for a in register['argv'] if a not in ('--config', CONFIG_PATH,
                                                                    '--instance',
                                                                    'http://127.0.0.1:13300')]
        register['argv'] += [f'--config={CONFIG_PATH}', '--instance=http://127.0.0.1:13300']
        self.assert_clean(profiles=variant(copy.deepcopy(GOOD_CONFIG), register=register))
        service = copy.deepcopy(GOOD_SERVICE)
        service['environment'] = {}
        self.assert_clean(profiles=variant(copy.deepcopy(GOOD_CONFIG), service=service))

    def test_a_forbidden_service_environment_fails(self):
        for name in ('GITEA_RUNNER_LABELS', 'GITEA_RUNNER_REGISTRATION_TOKEN', 'HTTP_PROXY',
                     'https_proxy', 'No_Proxy', 'DOCKER_HOST', 'ACTIONS_RUNNER_HOOK_JOB_STARTED',
                     'OTEL_EXPORTER_OTLP_ENDPOINT', 'otel_sdk_disabled'):
            service = copy.deepcopy(GOOD_SERVICE)
            service['environment'][name] = 'x'
            self.assert_code('RUNNER_ENVIRONMENT', 'provisioning.ci_runner.service',
                             profiles=variant(copy.deepcopy(GOOD_CONFIG), service=service))

    def test_the_service_runs_the_daemon_on_the_declared_config(self):
        cases = [False, 'x', {'environment': ['A=1'], 'argv': GOOD_SERVICE['argv']},
                 {'environment': {}, 'argv': 'gitea-runner daemon'},
                 {'environment': {}, 'argv': ['gitea-runner', 'daemon']},
                 {'environment': {}, 'argv': ['gitea-runner', 'daemon', '--config']},
                 {'environment': {}, 'argv': ['gitea-runner', '--config', CONFIG_PATH]},
                 {'environment': {}, 'argv': GOOD_SERVICE['argv'] + ['--labels', 'x:host']},
                 {'environment': {}, 'argv': GOOD_SERVICE['argv'] + ['--labels=x:host']}]
        for service in cases:
            self.assert_code('RUNNER_ENVIRONMENT', 'provisioning.ci_runner.service',
                             profiles=variant(copy.deepcopy(GOOD_CONFIG), service=service))

    def test_the_register_call(self):
        good = GOOD_REGISTER['argv']

        def without(*tokens):
            return [a for a in good if a not in tokens]

        def swap(old, new):
            self.assertEqual(good.count(old), 1)
            return [new if a == old else a for a in good]

        token = '/run/aieh/ci-runner/registration-token'
        cases = [
            without('--token-file', token),
            swap(token, '/tmp/token'),
            without('--token-file', token) + ['--token-file=/var/lib/token'],
            swap(token, '/run/../etc/token'),
            good + ['--token', 'abc'],
            good + ['--token=abc'],
            without('--config', CONFIG_PATH),
            good + ['--labels', 'aieh-validation:host'],
            without('--instance', 'http://127.0.0.1:13300'),
            swap('http://127.0.0.1:13300', 'http://gitea.example:3000'),
            good + ['--ephemeral'],
            good + ['--ephemeral=true'],
            without('--no-interactive'),
            without('register'),
        ]
        for argv in cases:
            self.assert_code('REGISTRATION_INPUT', 'provisioning.ci_runner.register',
                             profiles=variant(copy.deepcopy(GOOD_CONFIG), register={'argv': argv}))
        for register in (False, 'x', {'argv': ' '.join(good)},
                         {'argv': good, 'environment': {'GITEA_RUNNER_REGISTRATION_TOKEN': 'x'}},
                         {'argv': good, 'environment': {'gitea_runner_registration_token': 'x'}},
                         {'argv': good, 'environment': 'TOKEN=x'}):
            self.assert_code('REGISTRATION_INPUT', 'provisioning.ci_runner.register',
                             profiles=variant(copy.deepcopy(GOOD_CONFIG), register=register))

    def test_ephemeral_follows_the_chosen_lifetime(self):
        p, _ = fresh()
        p['placement']['lifetime_choice'].update(mode='per-validation', runner='ephemeral')
        self.assert_code('REGISTRATION_INPUT', 'provisioning.ci_runner.register', profile=p,
                         profiles=variant(copy.deepcopy(GOOD_CONFIG)))
        register = copy.deepcopy(GOOD_REGISTER)
        register['argv'].append('--ephemeral')
        self.assert_clean(profile=p, profiles=variant(copy.deepcopy(GOOD_CONFIG), register=register))
        p, _ = fresh()
        del p['placement']['lifetime_choice']['mode']
        self.assert_code('REGISTRATION_INPUT', 'provisioning.ci_runner.register', profile=p,
                         profiles=variant(copy.deepcopy(GOOD_CONFIG)))

    def test_the_chosen_lifetime_is_a_declared_one(self):
        for mode, runner in (('forever', 'persistent'), ('shared', 'ephemeral'), (['shared'], None),
                             ('per-validation', 'persistent')):
            p, _ = fresh()
            p['placement']['lifetime_choice'].update(mode=mode, runner=runner)
            self.assert_code('SCHEMA', 'placement.lifetime_choice', profile=p)

    def test_the_policy_declares_the_environment_rule(self):
        def env(p):
            return p['runner_config']['environment']

        mutations = [lambda e: e['forbidden_names'].remove('DOCKER_HOST'),
                     lambda e: e['forbidden_names'].remove('GITEA_RUNNER_LABELS'),
                     lambda e: e['forbidden_prefixes'].remove('OTEL_'),
                     lambda e: e.update(forbidden_prefixes=[]),
                     lambda e: e.update(config_expansion='allowed'),
                     lambda e: e.pop('service_key')]
        for mutate in mutations:
            p, _ = fresh()
            mutate(env(p))
            self.assert_code('RUNNER_RULE_WEAK', 'runner_config.environment', profile=p)
        # The checker's own names and prefixes stay the floor for a variant even when the policy
        # drops one.
        for name in ('DOCKER_HOST', 'OTEL_TRACES_EXPORTER'):
            p, _ = fresh()
            env(p)['forbidden_names'].remove('DOCKER_HOST')
            env(p)['forbidden_prefixes'].remove('OTEL_')
            service = copy.deepcopy(GOOD_SERVICE)
            service['environment'][name] = 'x'
            self.assert_code('RUNNER_ENVIRONMENT', 'provisioning.ci_runner.service', profile=p,
                             profiles=variant(copy.deepcopy(GOOD_CONFIG), service=service))
        p, _ = fresh()
        env(p)['forbidden_names'] = [n.lower() for n in env(p)['forbidden_names']]
        found, problems = self.codes(profile=p)
        self.assertNotIn('RUNNER_RULE_WEAK', found, '\n'.join(map(str, problems)))
        p, _ = fresh()
        env(p)['status'] = 'assumed'
        self.assert_code('STATUS_INVALID', 'runner_config.environment', profile=p)

    def test_the_policy_declares_the_token_input(self):
        def token_input(p):
            return p['registration']['token_input']

        mutations = [lambda t: t.update(flag='--token'), lambda t: t.update(path_prefix='/tmp/'),
                     lambda t: t['refused'].remove('GITEA_RUNNER_REGISTRATION_TOKEN'),
                     lambda t: t['refused'].remove('--token'), lambda t: t.pop('register_key')]
        for mutate in mutations:
            p, _ = fresh()
            mutate(token_input(p))
            self.assert_code('REGISTRATION_INPUT', 'registration.token_input', profile=p)
        p, _ = fresh()
        del p['registration']['token_input']
        self.assert_code('SCHEMA', 'registration.token_input', profile=p)
        self.assert_code('REGISTRATION_INPUT', 'registration.token_input', profile=p)

    def test_flag_helpers(self):
        self.assertEqual(ccp.flag_value(['a', '--x', 'v'], '--x'), 'v')
        self.assertEqual(ccp.flag_value(['--x=v'], '--x'), 'v')
        self.assertEqual(ccp.flag_value(['--x'], '--x'), '')
        self.assertEqual(ccp.flag_value(['--x', 'a', '--x=b'], '--x'), 'b')
        self.assertIsNone(ccp.flag_value(['--xy', 'v'], '--x'))
        self.assertTrue(ccp.has_flag(['--token=v'], '--token'))
        self.assertFalse(ccp.has_flag(['--token-file', 'v'], '--token'))
        self.assertEqual(ccp.expansions({'a': ['x', '$y'], '$b': 1, 'c': {'d': 'e$'}}),
                         ['a[1]', '$b', 'c.d'])


class Workflow(Base):

    def test_the_trigger_is_exactly_workflow_dispatch_with_three_inputs(self):
        self.assert_workflow('WORKFLOW_TRIGGER', 'on:\n  workflow_dispatch:\n',
                             'on:\n  push:\n    branches:\n      - main\n  workflow_dispatch:\n')
        self.assert_workflow('WORKFLOW_TRIGGER', '      bundle_sha256:\n', '      bundle:\n')
        self.assert_workflow('WORKFLOW_TRIGGER', 'on:\n  workflow_dispatch:\n',
                             'on:\n  pull_request_target:\n')

    def test_permissions(self):
        self.assert_workflow('WORKFLOW_PERMISSIONS', 'permissions: {}\n', '')
        self.assert_workflow('WORKFLOW_PERMISSIONS', 'permissions: {}\n',
                             'permissions:\n  contents: read\n')
        self.assert_workflow('WORKFLOW_PERMISSIONS', '    runs-on: aieh-validation\n',
                             '    runs-on: aieh-validation\n    permissions:\n      contents: write\n')

    def test_uses_fails(self):
        self.assert_workflow('WORKFLOW_USES', '      - id: quality\n',
                             '      - uses: actions/checkout@v4\n        run: echo x\n'
                             '      - id: quality\n')

    def test_secrets_and_vars_fail(self):
        self.assert_workflow('WORKFLOW_SECRETS', '      AIEH_EXCHANGE: /aieh/exchange\n',
                             '      AIEH_EXCHANGE: /aieh/exchange\n      TOKEN: secrets.DEPLOY\n')
        self.assert_workflow('WORKFLOW_SECRETS', 'set -euo pipefail\n          python3',
                             'set -euo pipefail\n          echo vars.X\n          python3')

    def test_runs_on(self):
        self.assert_workflow('WORKFLOW_RUNS_ON', 'runs-on: aieh-validation', 'runs-on: host')

    def test_container_and_services(self):
        for key in ('container', 'services'):
            self.assert_workflow('WORKFLOW_CONTAINER', '    timeout-minutes: 60\n',
                                 f'    timeout-minutes: 60\n    {key}:\n      image: debian\n')

    def test_interpolation(self):
        self.assert_workflow('WORKFLOW_INTERPOLATION', 'set -euo pipefail\n          python3',
                             'set -euo pipefail\n          echo ${{ github.event.pull_request.title }}'
                             '\n          python3')
        self.assert_workflow('WORKFLOW_INTERPOLATION', '      AIEH_EXCHANGE: /aieh/exchange\n',
                             '      AIEH_EXCHANGE: /aieh/exchange\n'
                             '      TITLE: ${{ gitea.event.head_commit.message }}\n')
        self.assert_workflow('WORKFLOW_INTERPOLATION', '${{ inputs.sha }}', '${{ inputs.repository }}')
        self.assert_workflow('WORKFLOW_INTERPOLATION', '        name: Validate the dispatch inputs\n',
                             '        name: Validate ${{ inputs.sha }}\n')

    def test_first_steps(self):
        self.assert_workflow('WORKFLOW_FIRST_STEPS', '- id: verify-bundle', '- id: verify-the-bundle')
        validate = WORKFLOW.index('      - id: validate-inputs')
        verify = WORKFLOW.index('      - id: verify-bundle')
        checkout = WORKFLOW.index('      - id: checkout')
        swapped = (WORKFLOW[:validate] + WORKFLOW[verify:checkout] + WORKFLOW[validate:verify]
                   + WORKFLOW[checkout:])
        self.assert_code('WORKFLOW_FIRST_STEPS', workflows={WORKFLOW_REL: swapped})
        self.assert_workflow('WORKFLOW_FIRST_STEPS', '{40}$', '{4,40}$')
        self.assert_workflow('WORKFLOW_FIRST_STEPS', 'git -C "$verify" bundle verify --quiet "$bundle"',
                             'true')
        self.assert_workflow('WORKFLOW_FIRST_STEPS', '[ "$(git -C proposal rev-parse HEAD)" = "$AIEH_SHA" ]',
                             'true')
        self.assert_workflow('WORKFLOW_FIRST_STEPS', '      AIEH_SHA: ${{ inputs.sha }}\n', '')

    def test_steps_cannot_be_skipped_or_softened(self):
        for key in ('if: false', 'continue-on-error: true'):
            self.assert_workflow('WORKFLOW_SCHEMA', '        name: Verify the staged bundle\n',
                                 f'        name: Verify the staged bundle\n        {key}\n')
        self.assert_workflow('WORKFLOW_SCHEMA', 'name: aieh-validation\n',
                             'name: aieh-validation\nenv:\n  X: y\n')

    def test_the_allowlist_is_the_profiles(self):
        self.assert_workflow('WORKFLOW_ALLOWLIST', 'AIEH_ALLOWED_REPOSITORIES: ""',
                             'AIEH_ALLOWED_REPOSITORIES: someone/else')
        p, _ = fresh()
        p['workflow']['allowed_repositories'] = ['aieh-authz-fixture/authz']
        self.assert_code('WORKFLOW_ALLOWLIST', profile=p)

    def test_the_source_of_record_exists(self):
        self.assert_code('WORKFLOW_MISSING', workflows={})
        self.assert_code('WORKFLOW_SYNTAX', workflows={WORKFLOW_REL: WORKFLOW + 'jobs: twice\n'})
        self.assert_code('WORKFLOW_SYNTAX', workflows={WORKFLOW_REL: None})
        self.assert_code('WORKFLOW_SCHEMA', workflows={WORKFLOW_REL: '- a\n- b\n'})


class YamlSubset(unittest.TestCase):

    def test_the_committed_workflow_parses(self):
        doc = ccp.parse_yaml_subset(WORKFLOW)
        steps = doc['jobs']['validate']['steps']
        self.assertEqual([s['id'] for s in steps],
                         ['validate-inputs', 'verify-bundle', 'checkout', 'quality'])
        self.assertTrue(steps[0]['run'].startswith('set -euo pipefail\n'))
        self.assertEqual(steps[0]['env'], {'AIEH_ALLOWED_REPOSITORIES': ''})
        self.assertEqual(doc['jobs']['validate']['env']['GIT_CONFIG_NOSYSTEM'], '1')

    def test_supported_forms(self):
        doc = ccp.parse_yaml_subset("a: 'it''s'\nb: \"x\\ty\"\nc: []\nd:\n  - 1\n  -\n    e: f\n"
                                    'g: |-\n  one\n\n  two\nh:\n')
        self.assertEqual(doc, {'a': "it's", 'b': 'x\ty', 'c': [], 'd': ['1', {'e': 'f'}],
                               'g': 'one\n\ntwo', 'h': None})

    def test_unsupported_forms_fail(self):
        for text in ('a: &x 1\n', 'a: *x\n', 'a: !!str 1\n', 'a: [1, 2]\n', 'a: {b: 1}\n',
                     'a: >\n  folded\n', 'a: 1 # comment\n', 'a: b: c\n', '\ta: 1\n', 'a: 1\na: 2\n',
                     '---\na: 1\n', '"a": 1\n', ' a: 1\n', 'a: "x\n', "a: 'x\n", 'a:\n  - 1\n  b: 2\n',
                     'a:\n  b: 1\n   c: 2\n', 'a: |\n    x\n  y\n', '', '# only\n', 'a: 1\nb\n'):
            with self.assertRaises(ccp.YamlSubsetError, msg=repr(text)):
                ccp.parse_yaml_subset(text)


class Gitea(Base):

    def test_actions_only_on_the_governance_repository(self):
        p, _ = fresh()
        item(p['gitea']['repositories'], 'repository', 'aieh-authz-fixture/authz')[
            'actions_enabled'] = True
        self.assert_code('GITEA_ACTIONS_SCOPE', 'aieh-authz-fixture/authz', profile=p)
        p, _ = fresh()
        p['gitea']['every_other_repository']['actions_enabled'] = True
        self.assert_code('GITEA_ACTIONS_SCOPE', 'every_other_repository', profile=p)
        p, _ = fresh()
        p['gitea']['instance']['default_actions_url'] = 'github'
        self.assert_code('GITEA_ACTIONS_SCOPE', 'gitea.instance', profile=p)
        p, _ = fresh()
        item(p['gitea']['repositories'], 'role', 'governance')['actions_enabled'] = False
        self.assert_code('GITEA_ACTIONS_SCOPE', 'quality-workflows', profile=p)
        p, _ = fresh()
        item(p['gitea']['repositories'], 'role', 'governance')['role'] = 'proposal'
        self.assert_code('GITEA_ACTIONS_SCOPE', 'gitea.repositories', profile=p)

    def test_no_public_repository(self):
        p, _ = fresh()
        p['gitea']['public_repositories'] = ['aieh-governance/open']
        self.assert_code('GITEA_PUBLIC_REPO', profile=p)
        p, _ = fresh()
        item(p['gitea']['repositories'], 'role', 'governance')['private'] = False
        self.assert_code('GITEA_PUBLIC_REPO', profile=p)
        p, _ = fresh()
        p['gitea']['every_other_repository']['private'] = False
        self.assert_code('GITEA_PUBLIC_REPO', profile=p)

    def test_the_governance_protection_is_complete(self):
        for rule in ccp.PROTECTIONS:
            p, _ = fresh()
            item(p['gitea']['repositories'], 'role', 'governance')['protections'][rule] = False
            self.assert_code('GITEA_PROTECTION', profile=p)

    def test_token_mode_and_ceiling(self):
        for where in ('owners', 'repositories'):
            _, q = fresh()
            q['ceilings'][where][0]['token_permission_mode'] = 'permissive'
            self.assert_code('GITEA_TOKEN_MODE', where, policy=q)
            _, q = fresh()
            q['ceilings'][where][0]['max_token_permissions']['code'] = 'read'
            self.assert_code('GITEA_CEILING', where, policy=q)
            _, q = fresh()
            del q['ceilings'][where][0]['max_token_permissions']['projects']
            self.assert_code('GITEA_CEILING', where, policy=q)
        _, q = fresh()
        q['ceilings']['repositories'][0]['override_owner_config'] = True
        self.assert_code('GITEA_CEILING', 'repositories', policy=q)
        _, q = fresh()
        q['ceilings']['workflow_permissions']['top_level'] = 'read-all'
        self.assert_code('GITEA_CEILING', 'workflow_permissions', policy=q)
        _, q = fresh()
        q['ceilings']['owners'] = []
        self.assert_code('GITEA_CEILING', 'ceilings', policy=q)

    def test_no_cross_repository_grant(self):
        cases = [('owners', 0, 'allowed_cross_repo_ids'), ('repositories', 0, 'collaborative_owner_ids')]
        for where, n, key in cases:
            _, q = fresh()
            q['ceilings'][where][n][key] = [7]
            self.assert_code('GITEA_CROSS_REPO', where, policy=q)
        for key, field in (('every_owner', 'allowed_cross_repo_ids'),
                           ('every_repository', 'collaborative_owner_ids')):
            _, q = fresh()
            q['ceilings'][key][field] = [3]
            self.assert_code('GITEA_CROSS_REPO', key, policy=q)

    def test_no_secret_or_variable(self):
        for key in ccp.SECRET_SETS:
            p, _ = fresh()
            p['gitea']['secrets'][key] = ['DEPLOY_KEY']
            self.assert_code('GITEA_SECRETS', key, profile=p)


class ProxyRegistrationActs(Base):

    def test_the_proxy_admits_exactly_the_runner_rpc(self):
        p, _ = fresh()
        p['proxy']['allow'].append({'method': 'POST', 'path': '/api/actions_pipeline/*'})
        self.assert_code('PROXY_ALLOWLIST', 'proxy.allow', profile=p)
        p, _ = fresh()
        item(p['proxy']['allow'], 'path', '/api/actions/runner.v1.RunnerService/Register').pop('window')
        self.assert_code('PROXY_ALLOWLIST', 'proxy.allow', profile=p)
        p, _ = fresh()
        p['proxy']['allow'].append(copy.deepcopy(p['proxy']['allow'][0]))
        self.assert_code('PROXY_ALLOWLIST', 'proxy.allow', profile=p)
        p, _ = fresh()
        p['proxy']['deny'].remove('/api/v1/*')
        self.assert_code('PROXY_ALLOWLIST', 'proxy.deny', profile=p)

    def test_the_registration_token_is_reset_after_registration(self):
        p, _ = fresh()
        p['registration']['procedure'].pop()
        self.assert_code('REGISTRATION_RESET', 'registration.procedure', profile=p)
        p, _ = fresh()
        p['registration']['procedure'].pop(0)
        self.assert_code('REGISTRATION_RESET', 'registration.procedure', profile=p)
        p, _ = fresh()
        item(p['registration']['procedure'], 'step', 'register')['step'] = 'enrol'
        self.assert_code('REGISTRATION_RESET', 'registration.procedure', profile=p)

    def test_the_fallback_is_never_in_force(self):
        # The Owner's direction of 2026-11-10 (decision 0016, dated note, point 1): a token
        # standing between provisionings is no path to a live runner, disclosed or not.
        for value in (True, 'yes', 1):
            p, _ = fresh()
            p['registration']['fallback']['in_force'] = value
            p['registration']['fallback']['disclosure'] = 'ci-d2'
            self.assert_code('REGISTRATION_RESET', 'registration.fallback', profile=p)
        p, _ = fresh()
        del p['registration']['fallback']
        found, problems = self.codes(profile=p)
        self.assertNotIn('REGISTRATION_RESET', found, '\n'.join(map(str, problems)))

    def test_an_unverified_reset_blocks_the_live_runner(self):
        p, _ = fresh()
        del p['registration']['live_gate']
        self.assert_code('SCHEMA', 'registration.live_gate', profile=p)
        self.assert_code('REGISTRATION_RESET', 'registration.live_gate', profile=p)
        for key, value in (('on_unverified', 'warn'), ('on_unverified', None), ('alternatives', []),
                           ('alternatives', [5]), ('verify_at', 'Q-02.3.1'),
                           ('verify_at', ['Q-02.3.1'])):
            p, _ = fresh()
            p['registration']['live_gate'][key] = value
            self.assert_code('REGISTRATION_RESET', 'registration.live_gate', profile=p)
        p, _ = fresh()
        p['registration']['live_gate']['verify_at'] = ['Q-02.2.2', 'Q-02.3.1']
        found, problems = self.codes(profile=p)
        self.assertNotIn('REGISTRATION_RESET', found, '\n'.join(map(str, problems)))
        p, _ = fresh()
        p['registration']['live_gate']['status'] = 'assumed'
        self.assert_code('STATUS_INVALID', 'registration.live_gate', profile=p)

    def test_an_owner_act_names_its_leaf(self):
        p, _ = fresh()
        item(p['owner_acts'], 'id', 'A-1')['requested_at'] = None
        self.assert_code('OWNER_ACT', 'A-1', profile=p)
        p, _ = fresh()
        item(p['owner_acts'], 'id', 'A-1')['requested_at'] = 'Q-99.9'
        self.assert_code('OWNER_ACT', 'A-1', profile=p)
        p, _ = fresh()
        item(p['owner_acts'], 'id', 'C-1')['status'] = 'done'
        self.assert_code('OWNER_ACT', 'C-1', profile=p)

    def test_an_observed_owner_act_cites_its_approval_verbatim(self):
        quote = 'The Owner approves the ci-control forward for one CI guest.'
        inputs = copy.copy(INPUTS)
        # The committed profile's own observed act (C-3) cites the log too.
        committed = [a['approval']['quote'] for a in PROFILE['owner_acts']
                     if a.get('status') == 'observed']
        inputs.files = FakeFiles(INPUTS.files, '# log\n\n' + ''.join(
            f'> {q}\n' for q in [quote] + committed))
        p, _ = fresh()
        act = item(p['owner_acts'], 'id', 'A-1')
        act['status'] = 'observed'
        self.assert_code('OWNER_ACT', 'A-1', profile=p, inputs=inputs)
        act['approval'] = {'link': ccp.BOOTSTRAP_LOG, 'quote': quote}
        found, problems = self.codes(profile=p, inputs=inputs)
        self.assertNotIn('OWNER_ACT', found, '\n'.join(map(str, problems)))
        act['approval']['quote'] = quote.replace('one', 'every')
        self.assert_code('OWNER_ACT', 'A-1', profile=p, inputs=inputs)

    def test_every_forward_and_listener_names_an_owner_act(self):
        for ident in ('ci-r1', 'ci-r6'):
            p, _ = fresh()
            del item(p['reach'], 'id', ident)['owner_act']
            self.assert_code('FORWARD_OWNER_ACT', ident, profile=p)
        for key in ('endpoint', 'proxy'):
            p, _ = fresh()
            p[key]['owner_act'] = 'A-9'
            self.assert_code('FORWARD_OWNER_ACT', key, profile=p)


class FactsAndRecords(Base):

    def test_a_fact_at_source_names_its_lines(self):
        for source in ([], [{'path': 'models/x.go'}], [{'path': '../x.go', 'lines': '1'}],
                       [{'path': 'x.go', 'lines': 'L12'}], None):
            _, q = fresh()
            item(q['gitea_facts'], 'id', 'G4')['source'] = source
            self.assert_code('FACT_UNSUPPORTED', 'G4', policy=q)
        _, q = fresh()
        item(q['gitea_facts'], 'id', 'G4')['verified'] = 'live'
        self.assert_code('FACT_UNSUPPORTED', 'G4', policy=q)
        _, q = fresh()
        item(q['gitea_facts'], 'id', 'G4').update(verified='live', evidence=['evidence/missing.md'])
        self.assert_code('LINK_MISSING', 'G4', policy=q)
        _, q = fresh()
        del item(q['gitea_facts'], 'id', 'A1')['verify_at']
        self.assert_code('FACT_UNSUPPORTED', 'A1', policy=q)
        _, q = fresh()
        item(q['gitea_facts'], 'id', 'G1')['verified'] = True
        self.assert_code('FACT_UNSUPPORTED', 'G1', policy=q)

    def test_the_archive_is_the_one_the_lock_pins(self):
        _, q = fresh()
        q['source_archive']['sha256'] = '0' * 64
        self.assert_code('FACT_ARCHIVE', policy=q)
        _, q = fresh()
        del q['source_archive']
        self.assert_code('FACT_ARCHIVE', policy=q)
        _, q = fresh()
        q['source_archive']['evidence'] = []
        self.assert_code('FACT_ARCHIVE', policy=q)

    def test_revocation_rows_equal_the_role_token_matrix(self):
        _, q = fresh()
        item(q['revocation'], 'credential', 'cred-runner-token')['revoker'] = 'owner'
        self.assert_code('REVOCATION_MISMATCH', 'cred-runner-token', policy=q)
        _, q = fresh()
        item(q['revocation'], 'credential', 'cred-ci-job-token')['triggers'].remove('expiry')
        self.assert_code('REVOCATION_MISMATCH', 'cred-ci-job-token', policy=q)
        _, q = fresh()
        q['revocation'] = [r for r in q['revocation'] if r['credential'] != 'cred-runner-registration']
        self.assert_code('REVOCATION_MISMATCH', 'cred-runner-registration', policy=q)
        _, q = fresh()
        item(q['revocation'], 'credential', 'cred-runner-token')['credential'] = 'cred-verifier-read'
        self.assert_code('REVOCATION_MISMATCH', 'cred-verifier-read', policy=q)

    def test_ids_resolve(self):
        p, q = fresh()
        item(p['lanes'], 'id', 'trusted-lane')['domains'].append('td-moon')
        self.assert_code('DANGLING_REF', 'trusted-lane', profile=p)
        p, _ = fresh()
        p['matrix_edits'][0]['edge'] = 'nm-no-such-edge'
        self.assert_code('DANGLING_REF', 'matrix_edits', profile=p)
        p, _ = fresh()
        p['matrix_edits'][0]['at'] = 'Q-99.1'
        self.assert_code('DANGLING_REF', 'matrix_edits', profile=p)
        p, _ = fresh()
        item(p['reach'], 'id', 'ci-r4')['credentials'] = ['cred-unknown']
        self.assert_code('DANGLING_REF', 'ci-r4', profile=p)
        _, q = fresh()
        q['disclosures'][0]['findings'] = ['fd-unknown']
        self.assert_code('DANGLING_REF', 'disclosures', policy=q)
        p, _ = fresh()
        p['relies_on_decisions'].append('0099')
        self.assert_code('DANGLING_REF', 'relies_on_decisions', profile=p)
        p, _ = fresh()
        p['decision']['record'] = 'decisions/0013-owner-ui-session-access-and-management-key-custody.md'
        self.assert_code('DANGLING_REF', 'profile.decision', profile=p)
        p, _ = fresh()
        p['acceptance'][0]['checks'].append('ci-unknown')
        self.assert_code('DANGLING_REF', 'acceptance', profile=p)
        p, _ = fresh()
        item(p['reach'], 'id', 'ci-r3')['owner_act'] = 'Z-1'
        self.assert_code('DANGLING_REF', 'ci-r3', profile=p)

    def test_a_committed_decision_record_must_be_linked(self):
        inputs = copy.copy(INPUTS)
        inputs.decisions = dict(INPUTS.decisions, **{'0016': '0016-hostile-ci.md'})
        p, q = fresh()  # the committed files link the record; an unlinked entry is the subject
        p['decision']['record'] = q['decision']['record'] = None
        self.assert_code('DECISION_UNLINKED', 'decision', inputs=inputs, profile=p, policy=q)

    def test_every_statement_has_a_status_and_a_leaf(self):
        p, _ = fresh()
        item(p['lanes'], 'id', 'validation-job')['status'] = 'hoped'
        self.assert_code('STATUS_INVALID', 'validation-job', profile=p)
        p, _ = fresh()
        del p['endpoint']['verify_at']
        self.assert_code('STATUS_INVALID', 'endpoint', profile=p)
        _, q = fresh()
        q['secret_rules'][0]['verify_at'] = 'Q-99.9'
        self.assert_code('STATUS_INVALID', 'secret_rules', policy=q)
        p, _ = fresh()
        p['proxy']['status'] = 'observed'
        self.assert_code('STATUS_INVALID', 'proxy', profile=p)

    def test_schema(self):
        p, q = fresh()
        p['exempt'] = True
        self.assert_code('SCHEMA', 'profile', profile=p)
        p, q = fresh()
        q['schema'] = 'v0'
        self.assert_code('SCHEMA', 'policy.schema', policy=q)
        p, _ = fresh()
        p['lanes'].pop()
        self.assert_code('SCHEMA', 'lanes', profile=p)
        _, q = fresh()
        item(q['credential_lanes'], 'credential', 'cred-uac-consent')['lane'] = 'elsewhere'
        self.assert_code('SCHEMA', 'cred-uac-consent', policy=q)
        self.assert_code('SCHEMA', profile='not a profile')

    def test_publication(self):
        p, _ = fresh()
        p['placement']['notes'] = 'see D:\\aieh-guest-state\\instances'
        self.assert_code('MACHINE_PATH', profile=p)
        self.assert_code('MACHINE_PATH', workflows={WORKFLOW_REL: WORKFLOW + '# C:\\Users\\x\n'})
        p, _ = fresh()
        p['lanes'][0]['name'] = 'Renamed'
        self.assert_code('README_STALE', profile=p)
        self.assert_code('README_STALE', readme=README.replace(ccp.GENERATED_BEGIN, ''))
        block = ccp.generated_block(README)
        self.assert_code('MACHINE_PATH', readme=README.replace(block, block + 'C:\\Users\\x\n'))
        p, _ = fresh()
        p['checks'][0]['codes'].pop()
        self.assert_code('CHECKS_STALE', profile=p)

    def test_wrong_types_never_crash(self):
        """Wrongly typed values give a named FAIL, never an exception."""
        values = (None, 'x', 5, [], {'a': 1}, [None])
        for value in values:
            for key in sorted(ccp.PROFILE_KEYS - {'notes'}):
                p, _ = fresh()
                p[key] = value
                self.codes(profile=p)
            for key in sorted(ccp.POLICY_KEYS - {'notes'}):
                _, q = fresh()
                q[key] = value
                self.codes(policy=q)
            for rows, keys in (('lanes', ('holds', 'reaches', 'domains', 'id')),
                               ('reach', ('kind', 'credentials', 'owner_act', 'from', 'to')),
                               ('owner_acts', ('id', 'requested_at', 'approval', 'status'))):
                for key in keys:
                    p, _ = fresh()
                    p[rows][0][key] = value
                    self.codes(profile=p)
                p, _ = fresh()
                p[rows] = [value]
                self.codes(profile=p)
            for rows in ('credential_lanes', 'task_tokens', 'gitea_facts', 'revocation',
                         'disclosures', 'secret_rules'):
                _, q = fresh()
                q[rows] = [value]
                self.codes(policy=q)
            for section in ('gitea', 'runner_config', 'workflow', 'registration', 'proxy'):
                p, _ = fresh()
                for key in list(p[section]):
                    p[section][key] = value
                self.codes(profile=p)
        found, _ = self.codes(profiles=variant('x'))
        self.assertIn('RUNNER_CONFIG', found)


class Guards(Base):
    """The schema and shape rules, each by the one mutation that only it catches."""

    def test_profile_and_record_shape(self):
        p, _ = fresh()
        p['schema'] = 'v0'
        self.assert_code('SCHEMA', 'profile.schema', profile=p)
        p, _ = fresh()
        p['sources'] = []
        self.assert_code('STATUS_INVALID', 'profile.sources', profile=p)
        p, _ = fresh()
        p['decision']['record'] = None  # only an unlinked decision needs a note
        p['decision']['note'] = ' '
        self.assert_code('SCHEMA', 'profile.decision', profile=p)
        p, _ = fresh()
        p['sources'].append('/etc/passwd')
        self.assert_code('LINK_INVALID', 'profile.sources', profile=p)
        p, _ = fresh()
        p['sources'][0] = p['sources'][0].split('#')[0] + '#no-such-anchor'
        self.assert_code('ANCHOR_MISSING', 'profile.sources', profile=p)

    def test_owner_act_shape(self):
        p, _ = fresh()
        p['owner_acts'] = []
        self.assert_code('SCHEMA', 'owner_acts', profile=p)
        p, _ = fresh()
        p['owner_acts'].append(copy.deepcopy(p['owner_acts'][0]))
        self.assert_code('SCHEMA', 'owner_acts.A-1', profile=p)
        p, _ = fresh()
        del item(p['owner_acts'], 'id', 'A-2')['class']
        self.assert_code('SCHEMA', 'owner_acts.A-2', profile=p)

    def test_lane_and_reach_shape(self):
        p, _ = fresh()
        item(p['lanes'], 'id', 'trusted-lane')['domains'] = []
        self.assert_code('SCHEMA', 'lanes.trusted-lane', profile=p)
        _, q = fresh()
        item(q['credential_lanes'], 'credential', 'cred-uac-consent')['reason'] = ''
        self.assert_code('SCHEMA', 'cred-uac-consent', policy=q)
        _, q = fresh()
        q['credential_lanes'].append(copy.deepcopy(item(q['credential_lanes'], 'credential',
                                                        'cred-owner-github')))
        self.assert_code('SCHEMA', 'cred-owner-github', policy=q)
        p, _ = fresh()
        item(p['reach'], 'id', 'ci-r3')['kind'] = 'teleport'
        self.assert_code('SCHEMA', 'reach.ci-r3', profile=p)
        _, q = fresh()
        item(q['task_tokens'], 'credential', 'cred-ci-runtime-token')['effective_permission'] = {}
        self.assert_code('TOKEN_ROW', 'cred-ci-runtime-token', policy=q)

    def test_gitea_and_ceiling_shape(self):
        p, _ = fresh()
        p['gitea']['repositories'].append(copy.deepcopy(item(p['gitea']['repositories'], 'role',
                                                             'governance')))
        self.assert_code('GITEA_ACTIONS_SCOPE', 'gitea.repositories', profile=p)
        p, _ = fresh()
        p['registration']['scope'] = 'aieh-authz-fixture/authz'
        self.assert_code('SCHEMA', 'registration.scope', profile=p)
        _, q = fresh()
        q['ceilings']['units'] = q['ceilings']['units'][:-1]
        self.assert_code('SCHEMA', 'ceilings.units', policy=q)
        _, q = fresh()
        q['secret_rules'][0]['rule'] = ''
        self.assert_code('SCHEMA', 'secret_rules', policy=q)
        p, _ = fresh()
        p['endpoint']['class'] = 'management'
        self.assert_code('SCHEMA', 'endpoint', profile=p)

    def test_fact_revocation_and_disclosure_shape(self):
        _, q = fresh()
        q['gitea_facts'].append(copy.deepcopy(item(q['gitea_facts'], 'id', 'G2')))
        self.assert_code('SCHEMA', 'gitea_facts.G2', policy=q)
        _, q = fresh()
        item(q['gitea_facts'], 'id', 'G2')['verify_live_at'] = 'Q-99.1'
        self.assert_code('DANGLING_REF', 'gitea_facts.G2', policy=q)
        _, q = fresh()
        q['source_archive']['lock'] = 'composition/candidates.json'
        self.assert_code('FACT_ARCHIVE', policy=q)
        _, q = fresh()
        item(q['revocation'], 'credential', 'cred-runner-token')['triggers'].append('whenever')
        self.assert_code('SCHEMA', 'revocation.cred-runner-token', policy=q)
        _, q = fresh()
        q['disclosures'][0]['text'] = ''
        self.assert_code('SCHEMA', 'disclosures.ci-d1', policy=q)
        inputs = copy.copy(INPUTS)
        roles = copy.deepcopy(INPUTS.role_tokens)
        for role in roles['roles']:
            role['revocation'] = [r for r in role['revocation'] if r['credential'] != 'cred-runner-token']
        inputs.role_tokens = roles
        self.assert_code('REVOCATION_MISMATCH', 'revocation.cred-runner-token', inputs=inputs)

    def test_workflow_shape(self):
        doc = ccp.parse_yaml_subset(WORKFLOW)
        for mutate in (lambda d: d.update(jobs={}),
                       lambda d: d['jobs'].update(validate='a job'),
                       lambda d: d['jobs']['validate'].update(strategy={'max-parallel': '1'}),
                       lambda d: d['jobs']['validate'].update(steps=[]),
                       lambda d: d['jobs']['validate']['steps'].append('a step'),
                       lambda d: d['jobs']['validate']['steps'][3].pop('run')):
            d = copy.deepcopy(doc)
            mutate(d)
            checker = ccp.Checker(*fresh(), INPUTS, None, {})
            checker.plan = set()
            checker.check_workflow(WORKFLOW_REL, d, PROFILE['workflow'])
            self.assertIn('WORKFLOW_SCHEMA', {x.code for x in checker.problems})

    def test_runner_option_and_config_shape(self):
        p, _ = fresh()
        p['runner_config']['options']['declared'].append('--cap-drop=NET_RAW')
        self.assert_code('RUNNER_RULE_WEAK', 'runner_config.options', profile=p)
        found, problems = self.codes(profiles=variant({'runner': 'x', 'cache': [], 'container': 5}))
        self.assertIn('RUNNER_CONFIG', found)
        found, problems = self.codes(profiles=variant('x'))
        self.assertTrue(any('not a mapping' in x.message for x in problems))
        config = copy.deepcopy(GOOD_CONFIG)
        config['container']['options'] = ['--cap-drop=ALL']
        found, problems = self.codes(profiles=variant(config))
        self.assertTrue(any('a string of options' in x.message for x in problems))

    def test_generated_block_markers(self):
        self.assertIsNone(ccp.generated_block('no markers'))
        self.assertIsNone(ccp.generated_block(ccp.GENERATED_BEGIN + ' and no end'))
        self.assertIsNone(ccp.generated_block(ccp.GENERATED_END + ' before ' + ccp.GENERATED_BEGIN))
        self.assertEqual(ccp.generated_block(ccp.GENERATED_BEGIN + 'x' + ccp.GENERATED_END), 'x')


if __name__ == '__main__':
    unittest.main()
