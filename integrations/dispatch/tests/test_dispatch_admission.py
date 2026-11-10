"""Tests for the dispatch create admission (plan leaf E-01.2.2, slice (a)).

Run from the repository root:

    python -I -B -m unittest discover -s integrations/dispatch/tests -v

The proof: path, resource and local-runtime bypasses never reach the OpenHands create. Every
create goes through an injected transport; every refusal below asserts that it was called zero
times, and the positive controls that it was called exactly once with the exact expected body.
The pipeline is the dispatcher's order (E-01.3.x): resolve, reserve_attempt, admit, send_create.

Everything lives in throwaway directories under the default TEMP (the E-01.2.1 fixture: the
design repository, the profiles, the manifests and the store), and the managed root is an
AIEH_DATA_ROOT inside it. No guest, Agent Server, network or LLM is used, and the default
managed root is never resolved.
"""
from pathlib import Path
import copy
import dataclasses
import hashlib
import importlib.util
import inspect
import itertools
import json
import os
import sys
import unittest

CATEGORY = 'integration'

HERE = Path(__file__).resolve().parent


def _load(name, path):
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


base = _load('test_dispatch_inputs', HERE / 'test_dispatch_inputs.py')
di = base.di
store_mod = base.store_mod
TEMPLATE_BYTES, ROUTES_BYTES = base.TEMPLATE_BYTES, base.ROUTES_BYTES
TEMPLATE = json.loads(TEMPLATE_BYTES)
REAL_PROFILE = 'strong-windows-qemu-whpx'
BS = chr(92)
RESERVED_REPOSITORIES = ('con', 'prn', 'aux', 'nul', 'com1', 'com0', 'lpt9')
DEFAULT = object()


def config(declared):
    return declared['provisioning']['agent_server']['config']['content']


def conversations(declared):
    return declared['provisioning']['agent_server']['conversations']


def template_bytes(change):
    body = copy.deepcopy(TEMPLATE)
    change(body)
    return json.dumps(body, indent=2).encode('utf-8')


def routes_bytes(change):
    data = json.loads(ROUTES_BYTES)
    change(data)
    return json.dumps(data, indent=1).encode('utf-8')


def create_entries(data):
    return [r for r in data['routes'] if (r['method'], r['path']) == ('POST', '/api/conversations')]


# The pinned server's recorded answers (E-01.3.1 request/response fixture).
EXCHANGE = json.loads((HERE / 'fixtures' / 'agent-server-1.60.1-exchange.json').read_bytes())


class CountingTransport:
    """The Agent Server, faked: answers GET /server_info (decision 0001's preconditions, checked
    before every create since E-01.3.1) with the pinned server's recorded answer and records it in
    ``info_calls``; records every other call, the create, in ``calls``."""

    def __init__(self, fail=None):
        self.calls, self.info_calls, self.fail = [], [], fail

    def __call__(self, method, path, body):
        if (method, path) == ('GET', '/server_info'):
            self.info_calls.append((method, path, body))
            return copy.deepcopy(EXCHANGE['server_info']['response'])
        self.calls.append((method, path, copy.deepcopy(body)))
        if self.fail is not None:
            raise self.fail
        return {'id': body['conversation_id'], 'status': 'created'}


class AdmissionFixture(base.Fixture):
    def setUp(self):
        super().setUp()
        self.names = itertools.count()
        self.root = self.case / 'aieh-root'
        self.workspaces = di.paths.resolve({'AIEH_DATA_ROOT': str(self.root)}, config={})
        self.category = Path(str(self.workspaces.paths['workspaces']))
        self.transport = CountingTransport()

    def fresh(self, stem):
        return f'{stem}-{next(self.names)}.json'

    def read_profile(self, name):
        return di.read_profile_file(name, profiles_root=self.profiles)

    def read_artifact(self, path):
        return di.read_profile_artifact(path, repo_root=self.tmp)

    def admit(self, resolved, manifest, workspaces=DEFAULT):
        return di.admit(resolved, manifest=manifest, workspaces=self.workspaces if workspaces is DEFAULT else workspaces,
                        read_profile=self.read_profile, read_artifact=self.read_artifact)

    def send(self, admitted, resolved, workspaces=DEFAULT):
        return di.send_create(admitted, resolved=resolved, transport=self.transport,
                              workspaces=self.workspaces if workspaces is DEFAULT else workspaces)

    def dispatch(self, request=None, manifest=None, sources=None):
        """The dispatcher's order: resolve, reserve_attempt, admit, send_create."""
        manifest = manifest or self.write_manifest(self.manifest_data(), self.fresh('manifest'))
        resolved = self.resolve(request, manifest, sources)
        self.store.reserve_attempt(resolved.attempt_identity(), resolved.intent(), actor='admission-test')
        return self.send(self.admit(resolved, manifest), resolved)

    def admitted(self):
        manifest = self.write_manifest(self.manifest_data(), self.fresh('manifest'))
        resolved = self.resolve(manifest=manifest)
        return manifest, resolved, self.admit(resolved, manifest)

    def fail_live(self):
        """A refused create: the dispatcher marks the reserved attempt failed (E-01.3.x)."""
        for reservation in self.store.attempts(['reserved']):
            self.store.transition(reservation.operation_key, 'failed', actor='admission-test', reason='refused')

    def assertDenied(self, code, call, *args, **kwargs):
        with self.assertRaises(di.DispatchRefused) as caught:
            call(*args, **kwargs)
        self.assertEqual(caught.exception.code, code, caught.exception.detail)
        self.assertIn(code, di.REFUSALS)
        self.assertEqual(caught.exception.to_json()['code'], code)
        self.assertEqual(self.transport.calls, [], 'a refusal must never reach the create')
        self.assertEqual(self.transport.info_calls, [], 'an admission refusal calls the transport zero times')
        return caught.exception

    def approve_variant(self, mutate=None, template=TEMPLATE_BYTES, routes=ROUTES_BYTES):
        """Rewrite strong-test-profile (its declaration, template and route allowlist) for this test
        and return a manifest approving the rewritten bytes."""
        directory = self.profiles / 'strong-test-profile'
        for path in (directory / 'profile.json', directory / 'agent-server' / 'conversation-create.json',
                     directory / 'agent-server' / 'routes.json'):
            self.addCleanup(path.write_bytes, path.read_bytes())
        base.write_agent_server(directory, template, routes)
        declared = json.loads(base.profile_bytes('strong-test-profile', template=template, routes=routes))
        if mutate is not None:
            mutate(declared)
        (directory / 'profile.json').write_bytes(json.dumps(declared, indent=2).encode('utf-8'))
        return self.write_manifest(self.manifest_data(), self.fresh('manifest'))

    def expected_body(self, resolved):
        body = copy.deepcopy(TEMPLATE)
        body['conversation_id'] = store_mod.conversation_id_for(resolved.attempt_identity().operation_key)
        return body

    def junction(self, link, target):
        if sys.platform != 'win32':
            self.skipTest('junctions are a Windows reparse point')
        import _winapi
        target.mkdir(parents=True, exist_ok=True)
        link.parent.mkdir(parents=True, exist_ok=True)
        _winapi.CreateJunction(str(target), str(link))
        self.addCleanup(os.rmdir, link)


class PositiveControlTests(AdmissionFixture):
    def test_admitted_create_reaches_the_transport_once_with_the_exact_body(self):
        manifest = self.write_manifest(self.manifest_data(), self.fresh('manifest'))
        resolved = self.resolve(manifest=manifest)
        reservation = self.store.reserve_attempt(resolved.attempt_identity(), resolved.intent(),
                                                 actor='admission-test').reservation
        admitted = self.admit(resolved, manifest)
        result = self.send(admitted, resolved)
        expected = self.expected_body(resolved)
        self.assertEqual(self.transport.calls, [('POST', '/api/conversations', expected)])
        self.assertEqual(self.transport.info_calls, [('GET', '/server_info', None)])
        self.assertEqual(result['id'], reservation.conversation_id)
        self.assertEqual(expected['conversation_id'], reservation.conversation_id)
        # The body is the pinned template with only the reserved conversation id changed.
        self.assertEqual({k: v for k, v in expected.items() if k != 'conversation_id'},
                         {k: v for k, v in TEMPLATE.items() if k != 'conversation_id'})
        self.assertEqual((expected['conversation_runtime'], expected['workspace']),
                         ('docker', {'kind': 'LocalWorkspace', 'working_dir': '/workspace'}))
        self.assertNotIn('memory', expected['container'])
        # The effective mount set the conversation container must have: exactly the declared binds.
        hexed = reservation.conversation_id.replace('-', '')
        self.assertEqual(admitted.mounts, [
            {'type': 'bind', 'source': f'/srv/scratch/openhands/conversations/{hexed}',
             'destination': f'/var/openhands/conversations/{hexed}', 'rw': True},
            {'type': 'bind', 'source': f'/srv/scratch/openhands/persistence/runtime-data/{hexed}/persistence',
             'destination': '/var/openhands/.openhands', 'rw': True},
            {'type': 'bind', 'source': f'/srv/scratch/openhands/persistence/runtime-data/{hexed}/workspace',
             'destination': '/workspace', 'rw': True}])
        # The host workspace: the planned workspace under the workspaces category; nothing created.
        attempt_id = store_mod.attempt_id_for(resolved.attempt_identity().operation_key)
        self.assertEqual(Path(admitted.host_workspace), self.root / 'persistent' / 'workspaces' / 'demo-app' /
                         'TASK-2' / attempt_id)
        self.assertFalse(self.root.exists())
        record = admitted.to_json()
        self.assertEqual((record['format'], record['route'], record['policy_digest']),
                         (di.ADMITTED_FORMAT, {'method': 'POST', 'path': '/api/conversations'},
                          resolved.policy_digest))
        self.assertEqual(record['create_template_sha256'], hashlib.sha256(TEMPLATE_BYTES).hexdigest())

    def test_the_checked_in_profile_declaration_admits_when_operational(self):
        """The real strong-windows-qemu-whpx declaration, only status.operational flipped in a
        throwaway copy: its configuration, ceilings, mounts, template and allowlist admit."""
        declared = json.loads((base.REPO / 'profiles' / REAL_PROFILE / 'profile.json').read_bytes())
        declared['status']['operational'] = True
        directory = self.profiles / REAL_PROFILE
        directory.mkdir()
        self.addCleanup(base.rmtree, directory)
        (directory / 'profile.json').write_bytes(json.dumps(declared, indent=2).encode('utf-8'))
        base.write_agent_server(directory)
        data = self.manifest_data()
        data['profiles'].append({'id': REAL_PROFILE, 'sha256': self.profile_sha(REAL_PROFILE)})
        data['bindings'][0]['profiles'].append(REAL_PROFILE)
        manifest = self.write_manifest(data, self.fresh('real'))
        resolved = self.resolve(self.request(profile=REAL_PROFILE), manifest)
        self.assertEqual(resolved.policy_inputs['admission']['caps'],
                         {'memory': '4g', 'cpus': 2.0, 'pids_limit': 512, 'max_concurrent_runs': 3})
        self.send(self.admit(resolved, manifest), resolved)
        self.assertEqual(self.transport.calls, [('POST', '/api/conversations', self.expected_body(resolved))])

    def test_ceiling_boundary_is_admitted(self):
        def at_ceiling(declared):  # 4 x 4 GiB = 16 GiB and 4 x 2.0 = 8 vCPU: equal, not above
            config(declared)['max_concurrent_runs'] = 4
        self.dispatch(manifest=self.approve_variant(at_ceiling))
        self.assertEqual(len(self.transport.calls), 1)

    def test_declared_cap_values_may_be_sent(self):
        """A template that sends the declared caps themselves (memory 4g, cpus 2.0) is admitted."""
        def caps(body):
            body['container'].update(memory='4g', cpus=2.0)
        template = template_bytes(caps)
        self.dispatch(manifest=self.approve_variant(template=template))
        self.assertEqual(self.transport.calls[0][2]['container'], {'browser': False, 'memory': '4g', 'cpus': 2.0})

    def test_existing_plain_directories_are_admitted(self):
        manifest, resolved, admitted = self.admitted()
        Path(admitted.host_workspace).mkdir(parents=True)
        self.send(self.admit(resolved, manifest), resolved)
        self.assertEqual(len(self.transport.calls), 1)

    def test_admission_is_deterministic(self):
        manifest = self.write_manifest(self.manifest_data(), self.fresh('manifest'))
        resolved = self.resolve(manifest=manifest)
        first, second = self.admit(resolved, manifest), self.admit(resolved, manifest)
        self.assertEqual(first, second)
        self.assertEqual(di._canonical(first.to_json()), di._canonical(second.to_json()))

    def test_no_parameter_takes_a_caller_choice(self):
        self.assertEqual(list(inspect.signature(di.admit).parameters),
                         ['resolved', 'manifest', 'workspaces', 'read_profile', 'read_artifact'])
        self.assertEqual(list(inspect.signature(di.send_create).parameters),
                         ['admitted', 'resolved', 'workspaces', 'transport'])

    def test_a_failed_create_is_never_retried_or_rerouted(self):
        self.transport = CountingTransport(fail=RuntimeError('422 from the server'))
        with self.assertRaises(RuntimeError):
            self.dispatch()
        self.assertEqual(len(self.transport.calls), 1)
        self.assertEqual(self.transport.calls[0][2]['conversation_runtime'], 'docker')


class WorkspaceDenialTests(AdmissionFixture):
    """Path bypasses: the planned workspace resolves under the workspaces category or is refused."""

    def tampered(self, planned):
        manifest, resolved, admitted = self.admitted()
        return manifest, dataclasses.replace(resolved, planned_workspace=planned), admitted

    def assertWorkspaceDenied(self, code, planned):
        manifest, resolved, admitted = self.tampered(planned)
        self.assertDenied(code, self.admit, resolved, manifest)
        self.assertDenied(code, self.send, admitted, resolved)

    def test_path_shapes_are_refused(self):
        _, resolved, _ = self.admitted()
        good = resolved.planned_workspace
        repository, work, attempt = good.split('/')
        cases = {
            'parent part': f'../{repository}/{work}/{attempt}',
            'inner parent': f'{repository}/../{work}/{attempt}',
            'dot part': f'./{repository}/{work}/{attempt}',
            'posix absolute': f'/{good}',
            'drive absolute': f'C:/{good}',
            'drive relative': f'C:{good}',
            'drive backslashes': f'C:{BS}{repository}{BS}{work}{BS}{attempt}',
            'UNC': f'{BS}{BS}server{BS}share{BS}{good}',
            'UNC forward': f'//server/share/{work}/{attempt}',
            'device namespace': f'{BS}{BS}?{BS}C:{BS}{good}',
            'backslash separators': f'{repository}{BS}{work}{BS}{attempt}',
            'alternate data stream': f'{repository}:evil/{work}/{attempt}',
            'stream on the leaf': f'{good}:$DATA',
            'trailing dot': f'{repository}./{work}/{attempt}',
            'trailing space': f'{repository} /{work}/{attempt}',
            'trailing dot on the leaf': f'{good}.',
            'trailing dot on the work id': f'{repository}/{work}./{attempt}',
            'upper-case repository': f'{repository.upper()}/{work}/{attempt}',
            'lower-case work id': f'{repository}/{work.lower()}/{attempt}',
            'upper-case uuid': f'{repository}/{work}/{attempt.upper()}',
            'fullwidth letters': ''.join(chr(ord(c) + 0xFEE0) if c.isalpha() else c for c in repository)
                                 + f'/{work}/{attempt}',
            'unicode hyphen': repository.replace('-', chr(0x2010)) + f'/{work}/{attempt}',
            'short name': f'DEMO-A~1/{work}/{attempt}',
            'trailing slash': f'{good}/',
            'empty part': f'{repository}//{work}/{attempt}',
            'extra part': f'{good}/extra',
            'missing part': f'{repository}/{work}',
            'NUL': f'{repository}{chr(0)}/{work}/{attempt}',
            'empty': '',
        }
        for name, planned in cases.items():
            with self.subTest(name):
                self.assertWorkspaceDenied('WORKSPACE_PATH_INVALID', planned)
        manifest, resolved, admitted = self.admitted()
        self.assertDenied('WORKSPACE_PATH_INVALID', self.admit,
                          dataclasses.replace(resolved, planned_workspace=None), manifest)

    def test_reserved_device_names_from_an_approved_repository(self):
        """The identifier grammar admits repository ids such as con; the resolver resolves them
        (E-01.2.1 section 8), and admission refuses their workspace."""
        data = self.manifest_data()
        sources = {}
        for name in RESERVED_REPOSITORIES:
            data['repositories'].append({'id': name})
            data['designs'].append({'repository': name, 'change': base.CHANGE, 'commit': self.commit})
            data['bindings'].append({'repository': name, 'stage': 'implement',
                                     'profiles': ['strong-test-profile'], 'catalog_pins': ['builder-pin']})
            sources[name] = self.sources['demo-app']
        manifest = self.write_manifest(data, self.fresh('reserved'))
        for name in RESERVED_REPOSITORIES:
            with self.subTest(name):
                resolved = self.resolve(self.request(repository=name), manifest, sources)
                self.assertTrue(resolved.planned_workspace.startswith(f'{name}/'))
                refusal = self.assertDenied('WORKSPACE_RESERVED_NAME', self.admit, resolved, manifest)
                self.assertEqual(refusal.context['part'], name)

    def test_reserved_device_names_in_any_part_and_form(self):
        _, resolved, _ = self.admitted()
        repository, work, attempt = resolved.planned_workspace.split('/')
        for planned in (f'con.txt/{work}/{attempt}', f'CON/{work}/{attempt}', f'Nul.tar.gz/{work}/{attempt}',
                        f'lpt1 /{work}/{attempt}', f'com{chr(0xB9)}/{work}/{attempt}', f'COM9.x/{work}/{attempt}',
                        f'conin$/{work}/{attempt}', f'{repository}/AUX/{attempt}', f'{repository}/{work}/prn.log',
                        f'{repository}{BS}con{BS}{attempt}'):
            with self.subTest(planned):
                self.assertWorkspaceDenied('WORKSPACE_RESERVED_NAME', planned)

    def test_another_attempt_s_workspace(self):
        _, resolved, _ = self.admitted()
        repository, work, attempt = resolved.planned_workspace.split('/')
        other = store_mod.attempt_id_for('attempt/v1/TASK-9/x@y/implement/1')
        for planned in (f'{repository}/{work}/{other}', f'other-app/{work}/{attempt}',
                        f'{repository}/TASK-3/{attempt}'):
            with self.subTest(planned):
                self.assertWorkspaceDenied('WORKSPACE_NOT_PLANNED', planned)

    def test_admitted_host_workspace_altered(self):
        manifest, resolved, admitted = self.admitted()
        for host in (str(self.case / 'elsewhere'), f'C:{BS}Windows', str(self.category)):
            with self.subTest(host):
                self.assertDenied('WORKSPACE_NOT_PLANNED', self.send,
                                  dataclasses.replace(admitted, host_workspace=host), resolved)
        self.assertDenied('WORKSPACE_NOT_PLANNED', self.send,
                          dataclasses.replace(admitted, planned_workspace='other-app/TASK-2/x'), resolved)

    def test_links_junctions_and_files_on_the_path(self):
        manifest, resolved, admitted = self.admitted()
        repository, work, attempt = resolved.planned_workspace.split('/')
        elsewhere = self.case / 'elsewhere'
        cases = {
            'junction at the repository': lambda: self.junction(self.category / repository, elsewhere),
            'junction at the work': lambda: self.junction(self.category / repository / work, elsewhere),
            'junction at the attempt': lambda: self.junction(self.category / repository / work / attempt, elsewhere),
            'junction at the category': lambda: self.junction(self.category, elsewhere),
            'file at the attempt': lambda: (
                (self.category / repository / work).mkdir(parents=True),
                (self.category / repository / work / attempt).write_bytes(b'')),
        }
        for name, plant in cases.items():
            with self.subTest(name):
                plant()
                self.assertDenied('WORKSPACE_PATH_UNSAFE', self.admit, resolved, manifest)
                # Planted after admission: refused again immediately before the create.
                self.assertDenied('WORKSPACE_PATH_UNSAFE', self.send, admitted, resolved)
                self.doCleanups()
                if self.root.exists():
                    base.rmtree(self.root)

    def test_symbolic_link_on_the_path(self):
        manifest, resolved, admitted = self.admitted()
        repository = resolved.planned_workspace.split('/')[0]
        target = self.case / 'elsewhere'
        target.mkdir()
        self.category.mkdir(parents=True)
        try:
            os.symlink(target, self.category / repository, target_is_directory=True)
        except OSError as exc:  # Windows needs the symlink privilege or developer mode
            self.skipTest(f'cannot create a symbolic link here: {type(exc).__name__}')
        self.assertDenied('WORKSPACE_PATH_UNSAFE', self.admit, resolved, manifest)
        self.assertDenied('WORKSPACE_PATH_UNSAFE', self.send, admitted, resolved)

    def test_workspaces_category_unavailable(self):
        manifest, resolved, admitted = self.admitted()
        other_platform = 'linux' if sys.platform == 'win32' else 'win32'
        anchor = '/srv/repo' if other_platform == 'linux' else 'C:/repo'
        foreign = di.paths.resolve({'AIEH_DATA_ROOT': anchor + '-data'}, platform=other_platform,
                                   repo_root=anchor, config={})
        for workspaces in (None, str(self.category), foreign):
            with self.subTest(repr(workspaces)[:40]):
                self.assertDenied('WORKSPACE_CATEGORY_UNAVAILABLE', self.admit, resolved, manifest, workspaces)
                self.assertDenied('WORKSPACE_CATEGORY_UNAVAILABLE', self.send, admitted, resolved, workspaces)


class ProfilePolicyDenialTests(AdmissionFixture):
    """Resource, runtime, mount and route bypasses declared by an approved profile: refused at
    resolution (before any reservation) or at admission, never at the create."""

    def assertProfileDenied(self, code, mutate=None, template=TEMPLATE_BYTES, routes=ROUTES_BYTES):
        manifest = self.approve_variant(mutate, template, routes)
        refusal = self.assertDenied(code, self.dispatch, manifest=manifest)
        return refusal

    def test_local_or_selectable_runtime_in_the_server_configuration(self):
        for name, key, value in (('local', 'conversation_runtime', 'local'),
                                 ('process', 'conversation_runtime', 'process'),
                                 ('absent', 'conversation_runtime', None),
                                 ('case variant', 'conversation_runtime', 'Docker'),
                                 ('selectable', 'conversation_runtime_selectable', True),
                                 ('selectable absent', 'conversation_runtime_selectable', None),
                                 ('selectable falsy zero', 'conversation_runtime_selectable', 0)):
            with self.subTest(name):
                self.assertProfileDenied('RUNTIME_NOT_DOCKER', lambda d, k=key, v=value: config(d).update({k: v}))
                self.assertEqual(self.store.attempts(), [])  # refused at resolution: nothing reserved

    def test_caps_above_the_ceilings(self):
        for name, changes in (('memory x runs', {'conversation_container_memory': '6g'}),
                              ('one run above', {'conversation_container_memory': '17g', 'max_concurrent_runs': 1}),
                              ('cpus x runs', {'conversation_container_cpus': 3.0}),
                              ('more runs', {'max_concurrent_runs': 5}),
                              ('megabytes', {'conversation_container_memory': '5462m'})):
            with self.subTest(name):
                self.assertProfileDenied('CAPS_ABOVE_CEILING', lambda d, c=changes: config(d).update(c))

        def lower_ceiling(declared):
            declared['ceilings']['vcpu'] = 4
        self.assertProfileDenied('CAPS_ABOVE_CEILING', lower_ceiling)

    def test_malformed_caps_or_ceilings(self):
        for name, mutate in (
                ('memory notation', lambda d: config(d).update(conversation_container_memory='4 GiB')),
                ('memory absent', lambda d: config(d).pop('conversation_container_memory')),
                ('cpus boolean', lambda d: config(d).update(conversation_container_cpus=True)),
                ('cpus zero', lambda d: config(d).update(conversation_container_cpus=0)),
                ('pids absent', lambda d: config(d).pop('conversation_container_pids_limit')),
                ('pids zero', lambda d: config(d).update(conversation_container_pids_limit=0)),
                ('runs string', lambda d: config(d).update(max_concurrent_runs='3')),
                ('ceilings absent', lambda d: d.pop('ceilings')),
                ('vcpu float', lambda d: d['ceilings'].update(vcpu=8.0)),
                ('no agent server', lambda d: d.pop('provisioning'))):
            with self.subTest(name):
                self.assertProfileDenied('PROFILE_ADMISSION_INVALID', mutate)

    def test_mount_policy_outside_the_rules(self):
        hexed = '{conversation_hex}'

        def bind(index, **changes):
            return lambda d: conversations(d)['mounts'][index].update(changes)

        def drop_socket(declared):
            conversations(declared)['forbidden_sources'].remove('/run/docker.sock')

        def duplicate(declared):
            conversations(declared)['mounts'][0]['destination'] = '/workspace'

        for name, mutate in (
                ('the docker socket', bind(0, source='/run/docker.sock')),
                ('moby data root', bind(0, source='/srv/scratch/docker/overlay2')),
                ('outside the source root', bind(0, source=f'/srv/scratch/other/{hexed}')),
                ('the source root itself', bind(0, source='/srv/scratch/openhands')),
                ('a parent of a forbidden source', lambda d: (conversations(d).update(source_root='/srv'),
                                                              bind(0, source='/srv/scratch')(d))),
                ('a parent part', bind(0, source=f'/srv/scratch/openhands/../docker/{hexed}')),
                ('an unknown placeholder', bind(0, source='/srv/scratch/openhands/{other}')),
                ('a relative destination', bind(1, destination='var/openhands')),
                ('a duplicate destination', duplicate),
                ('no working directory bind', bind(2, destination='/work')),
                ('the socket no longer forbidden', drop_socket)):
            with self.subTest(name):
                self.assertProfileDenied('MOUNT_POLICY_INVALID', mutate)
        for name, mutate in (('a volume', bind(0, type='volume')), ('rw string', bind(0, rw='yes')),
                             ('no binds', lambda d: conversations(d).update(mounts=[])),
                             ('an extra key', bind(0, propagation='shared'))):
            with self.subTest(name):
                self.assertProfileDenied('PROFILE_ADMISSION_INVALID', mutate)

    def test_route_not_allowlisted(self):
        def not_used(data):
            create_entries(data)[0]['dispatcher'] = 'not-used'

        def validation(data):
            create_entries(data)[0]['dispatcher'] = 'validation'

        def duplicated(data):
            data['routes'].append(dict(create_entries(data)[0]))

        def absent(data):
            data['routes'] = [r for r in data['routes'] if r not in create_entries(data)]

        for name, change in (('not-used', not_used), ('validation only', validation),
                             ('listed twice', duplicated), ('absent', absent)):
            with self.subTest(name):
                self.assertProfileDenied('ROUTE_NOT_ALLOWLISTED', routes=routes_bytes(change))
                self.assertEqual(len(self.store.attempts(['reserved'])), 1)  # reserved, refused before the create
                self.fail_live()

    def test_pinned_artifacts(self):
        self.assertProfileDenied('PROFILE_ARTIFACT_INVALID', routes=routes_bytes(lambda d: d.update(schema='x/v1')))
        self.fail_live()
        self.assertProfileDenied('PROFILE_ARTIFACT_INVALID', template=b'[1, 2]')
        self.fail_live()
        self.assertProfileDenied('PROFILE_ARTIFACT_INVALID', template=b'{"a": 1, "a": 2}')
        self.fail_live()
        # Changed after approval: the approved profile pins the earlier bytes.
        manifest = self.approve_variant()
        directory = self.profiles / 'strong-test-profile' / 'agent-server'
        (directory / 'routes.json').write_bytes(ROUTES_BYTES + b' ')
        self.assertDenied('PROFILE_ARTIFACT_DRIFTED', self.dispatch, manifest=manifest)
        self.fail_live()
        (directory / 'routes.json').unlink()
        self.assertDenied('PROFILE_ARTIFACT_MISSING', self.dispatch, manifest=manifest)
        self.fail_live()
        (directory / 'routes.json').write_bytes(ROUTES_BYTES)
        # A pin outside the profile's own directory is not a pin.
        for path in ('profiles/strong-dormant/agent-server/routes.json', 'profiles/strong-test-profile/../x.json',
                     'C:/x/routes.json'):
            with self.subTest(path):
                def elsewhere(declared, p=path):
                    declared['provisioning']['agent_server']['admission']['routes']['path'] = p
                self.assertProfileDenied('PROFILE_ADMISSION_INVALID', elsewhere)

    def test_template_outside_the_policy(self):
        for name, change, code in (
                ('local runtime', lambda b: b.update(conversation_runtime='local'), 'RUNTIME_NOT_DOCKER'),
                ('runtime omitted', lambda b: b.pop('conversation_runtime'), 'RUNTIME_NOT_DOCKER'),
                ('host working dir', lambda b: b['workspace'].update(working_dir='/srv/scratch'),
                 'WORKING_DIR_NOT_ALLOWED'),
                ('windows host path', lambda b: b['workspace'].update(working_dir='C:/Users'),
                 'WORKING_DIR_NOT_ALLOWED'),
                ('remote workspace', lambda b: b['workspace'].update(kind='RemoteWorkspace'),
                 'WORKING_DIR_NOT_ALLOWED'),
                ('memory override', lambda b: b['container'].update(memory='8g'), 'CAPS_OVERRIDE_FORBIDDEN'),
                ('cpus override', lambda b: b['container'].update(cpus=8), 'CAPS_OVERRIDE_FORBIDDEN'),
                ('pids field', lambda b: b['container'].update(pids_limit=100000), 'CAPS_OVERRIDE_FORBIDDEN'),
                ('container volumes', lambda b: b['container'].update(volumes=['/:/host']), 'MOUNTS_NOT_DECLARED'),
                ('initial message', lambda b: b.update(initial_message={'role': 'user'}), 'BODY_FIELD_UNKNOWN'),
                ('container image', lambda b: b['container'].update(image='x:latest'), 'BODY_FIELD_UNKNOWN')):
            with self.subTest(name):
                self.assertProfileDenied(code, template=template_bytes(change))
                self.fail_live()


class TamperDenialTests(AdmissionFixture):
    """Defence in depth: an admitted request altered after construction, or a resolved record
    altered after reservation, is refused immediately before the transport."""

    def assertBodyDenied(self, code, change):
        _, resolved, admitted = self.admitted()
        body = admitted.body
        change(body)
        altered = dataclasses.replace(admitted, body_json=json.dumps(body))
        return self.assertDenied(code, self.send, altered, resolved)

    def test_body_altered(self):
        for name, change, code in (
                ('runtime local', lambda b: b.update(conversation_runtime='local'), 'RUNTIME_NOT_DOCKER'),
                ('runtime removed', lambda b: b.pop('conversation_runtime'), 'RUNTIME_NOT_DOCKER'),
                ('runtime list', lambda b: b.update(conversation_runtime=['docker']), 'RUNTIME_NOT_DOCKER'),
                ('working dir root', lambda b: b['workspace'].update(working_dir='/'), 'WORKING_DIR_NOT_ALLOWED'),
                ('host working dir', lambda b: b['workspace'].update(working_dir=f'C:{BS}Users'),
                 'WORKING_DIR_NOT_ALLOWED'),
                ('workspace host path field', lambda b: b['workspace'].update(host_path='/srv'),
                 'WORKING_DIR_NOT_ALLOWED'),
                ('memory above', lambda b: b['container'].update(memory='64g'), 'CAPS_OVERRIDE_FORBIDDEN'),
                ('memory as bytes', lambda b: b['container'].update(memory=4294967296), 'CAPS_OVERRIDE_FORBIDDEN'),
                ('cpus above', lambda b: b['container'].update(cpus=8.0), 'CAPS_OVERRIDE_FORBIDDEN'),
                ('cpus as integer', lambda b: b['container'].update(cpus=2), 'CAPS_OVERRIDE_FORBIDDEN'),
                ('pids', lambda b: b['container'].update(pids_limit=-1), 'CAPS_OVERRIDE_FORBIDDEN'),
                ('top-level memory', lambda b: b.update(memory='64g'), 'CAPS_OVERRIDE_FORBIDDEN'),
                ('top-level mounts', lambda b: b.update(mounts=[{'source': '/'}]), 'MOUNTS_NOT_DECLARED'),
                ('container binds', lambda b: b['container'].update(binds=['/run/docker.sock:/s']),
                 'MOUNTS_NOT_DECLARED'),
                ('runtime selector field', lambda b: b.update(runtime='local'), 'RUNTIME_NOT_DOCKER'),
                ('working dir field', lambda b: b.update(working_dir='/'), 'WORKING_DIR_NOT_ALLOWED'),
                ('initial message', lambda b: b.update(initial_message={'content': 'x'}), 'BODY_FIELD_UNKNOWN'),
                ('agent', lambda b: b.update(agent={'kind': 'x'}), 'BODY_FIELD_UNKNOWN'),
                ('container network', lambda b: b['container'].update(network='host'), 'BODY_FIELD_UNKNOWN'),
                ('tools added', lambda b: b['agent_settings'].update(tools=[{'name': 'terminal'}]),
                 'BODY_NOT_TEMPLATE'),
                ('llm added', lambda b: b['agent_settings'].update(llm={'model': 'x'}), 'BODY_NOT_TEMPLATE'),
                ('tags changed', lambda b: b.update(tags={'aieh': 'other'}), 'BODY_NOT_TEMPLATE'),
                ('browser on', lambda b: b['container'].update(browser=True), 'BODY_NOT_TEMPLATE'),
                ('container removed', lambda b: b.pop('container'), 'BODY_NOT_TEMPLATE'),
                ('autotitle on', lambda b: b.update(autotitle=True), 'BODY_NOT_TEMPLATE'),
                ('conversation id', lambda b: b.update(conversation_id='929f0d8a-f3d8-4da3-8ac3-9d0017709d71'),
                 'CONVERSATION_ID_MISMATCH')):
            with self.subTest(name):
                self.assertBodyDenied(code, change)

    def test_body_not_an_object_or_not_strict_json(self):
        _, resolved, admitted = self.admitted()
        good = admitted.body_json
        for text in ('[]', 'NaN', '{"x": NaN}', good[:-1] + ',"tags":{}}', 'not json', '"docker"'):
            with self.subTest(text[:30]):
                self.assertDenied('BODY_MALFORMED', self.send, dataclasses.replace(admitted, body_json=text), resolved)
        self.assertDenied('BODY_MALFORMED', self.send, dataclasses.replace(admitted, body_json=None), resolved)

    def test_mounts_altered(self):
        _, resolved, admitted = self.admitted()
        mounts = admitted.mounts
        extra = mounts + [{'type': 'bind', 'source': '/run/docker.sock', 'destination': '/var/run/docker.sock',
                           'rw': True}]
        read_only = copy.deepcopy(mounts)
        read_only[2]['rw'] = False
        altered = copy.deepcopy(mounts)
        altered[2]['source'] = '/srv/scratch/openhands/persistence/runtime-data/other/workspace'
        for name, value in (('extra', extra), ('missing', mounts[:2]), ('reordered', mounts[::-1]),
                            ('read only', read_only), ('altered source', altered), ('none', [])):
            with self.subTest(name):
                self.assertDenied('MOUNTS_NOT_DECLARED', self.send,
                                  dataclasses.replace(admitted, mounts_json=json.dumps(value)), resolved)

    def test_route_altered(self):
        _, resolved, admitted = self.admitted()
        for method, path in (('POST', '/api/conversations/{conversation_id}/runtime/reprovision'),
                             ('PUT', '/api/conversations'), ('POST', '/api/bash/execute_bash_command'),
                             ('POST', '/api/conversations/'), ('post', '/api/conversations')):
            with self.subTest(f'{method} {path}'):
                self.assertDenied('ROUTE_NOT_ALLOWLISTED', self.send,
                                  dataclasses.replace(admitted, method=method, path=path), resolved)

    def test_template_bytes_altered(self):
        _, resolved, admitted = self.admitted()
        swapped = template_bytes(lambda b: b.update(conversation_runtime='local'))
        self.assertDenied('PROFILE_ARTIFACT_DRIFTED', self.send,
                          dataclasses.replace(admitted, template_bytes=swapped), resolved)

    def test_identity_or_digest_altered(self):
        _, resolved, admitted = self.admitted()
        for field, value in (('policy_digest', '0' * 64), ('operation_key', 'attempt/v1/TASK-9/x@y/implement/1'),
                             ('conversation_id', '00000000-0000-5000-8000-000000000000')):
            with self.subTest(field):
                self.assertDenied('ADMISSION_MISMATCH', self.send,
                                  dataclasses.replace(admitted, **{field: value}), resolved)

    def forged(self, resolved, change):
        inputs = resolved.policy_inputs
        change(inputs['admission'])
        text = di._canonical(inputs)
        return dataclasses.replace(resolved, policy_inputs_json=text, policy_digest=di._sha256(text))

    def test_resolved_policy_altered(self):
        manifest, resolved, admitted = self.admitted()
        inputs = resolved.policy_inputs
        inputs['admission']['caps']['memory'] = '64g'
        unbound = dataclasses.replace(resolved, policy_inputs_json=di._canonical(inputs))
        self.assertDenied('ADMISSION_MISMATCH', self.admit, unbound, manifest)
        self.assertDenied('ADMISSION_MISMATCH', self.send, admitted, unbound)
        # Re-digested to look consistent: the approved profile does not declare it ...
        forged = self.forged(resolved, lambda a: a['caps'].update(memory='5g'))
        self.assertDenied('ADMISSION_MISMATCH', self.admit, forged, manifest)
        # ... and a forged pair whose policy breaks the ceilings is refused at the send as well.
        forged = self.forged(resolved, lambda a: a['caps'].update(memory='64g'))
        body = admitted.body
        body['container']['memory'] = '64g'
        pair = dataclasses.replace(admitted, policy_digest=forged.policy_digest, body_json=json.dumps(body))
        self.assertDenied('CAPS_ABOVE_CEILING', self.send, pair, forged)
        forged = self.forged(resolved, lambda a: a['runtime'].update(conversation_runtime='local'))
        pair = dataclasses.replace(admitted, policy_digest=forged.policy_digest)
        self.assertDenied('RUNTIME_NOT_DOCKER', self.send, pair, forged)
        forged = self.forged(resolved, lambda a: a['route'].update(path='/api/bash/execute_bash_command'))
        pair = dataclasses.replace(admitted, policy_digest=forged.policy_digest, path='/api/bash/execute_bash_command')
        self.assertDenied('ROUTE_NOT_ALLOWLISTED', self.send, pair, forged)
        forged = self.forged(resolved, lambda a: a['workspace'].update(working_dir='/srv'))
        body = admitted.body
        body['workspace']['working_dir'] = '/srv'
        pair = dataclasses.replace(admitted, policy_digest=forged.policy_digest, body_json=json.dumps(body))
        self.assertDenied('WORKING_DIR_NOT_ALLOWED', self.send, pair, forged)
        forged = self.forged(resolved, lambda a: a['mounts']['binds'].append(
            {'type': 'bind', 'source': '/run/docker.sock', 'destination': '/s', 'rw': True}))
        pair = dataclasses.replace(admitted, policy_digest=forged.policy_digest)
        self.assertDenied('MOUNT_POLICY_INVALID', self.send, pair, forged)

    def test_provenance(self):
        manifest, resolved, admitted = self.admitted()
        data = self.manifest_data()
        data['version'] = 8
        self.assertDenied('ADMISSION_MISMATCH', self.admit, resolved, self.write_manifest(data, self.fresh('v8')))
        target = self.profiles / 'strong-test-profile' / 'profile.json'
        self.addCleanup(target.write_bytes, target.read_bytes())
        target.write_bytes(target.read_bytes() + b' ')
        self.assertDenied('PROFILE_DRIFTED', self.admit, resolved, manifest)
        self.assertDenied('ADMISSION_MISMATCH', self.send, admitted,
                          dataclasses.replace(resolved, profile_digest='0' * 64))
        with self.assertRaises(TypeError):
            di.send_create(admitted.to_json(), resolved=resolved, workspaces=self.workspaces, transport=self.transport)
        with self.assertRaises(TypeError):
            di.admit(resolved.to_json(), manifest=manifest, workspaces=self.workspaces)
        self.assertEqual(self.transport.calls, [])


if __name__ == '__main__':
    unittest.main()
