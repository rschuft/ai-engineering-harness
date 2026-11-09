"""Tests for the trusted dispatch input resolver (plan leaf E-01.2.1).

Run from the repository root:

    python -I -B -m unittest discover -s integrations/dispatch/tests -v

Everything lives in throwaway directories under the default TEMP: the approved-input
manifests, the profile declarations (with the admission declaration E-01.2.2 reads, and copies
of the checked-in create template and route allowlist), the integration store and the OpenSpec design
repository (built by the planning fixture, ``two_task_fixture.build_repo``). Backlog.md is
its own recorded readiness output (``integrations/planning/tests/fixtures/readiness/``),
replayed in process. No live store, Backlog.md, guest, Gitea or network is used.
"""
from pathlib import Path
import copy
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

CATEGORY = 'integration'

HERE = Path(__file__).resolve().parent
DISPATCH = HERE.parent
REPO = DISPATCH.parents[1]
MODULE = DISPATCH / 'dispatch_inputs.py'
EXAMPLE = DISPATCH / 'examples' / 'approved-inputs.example.json'
PLANNING_TESTS = REPO / 'integrations' / 'planning' / 'tests'
READINESS = PLANNING_TESTS / 'fixtures' / 'readiness'


def _load(name, path):
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


di = _load('dispatch_inputs', MODULE)
store_mod = di.store
planning = di.planning
fx = _load('two_task_fixture', PLANNING_TESTS / 'two_task_fixture.py')
assert fx.adapter is planning, 'the fixture and the resolver must share one planning adapter'

WAIT_CEILING_S = 60  # bounds a hung child; the CLI normally answers in well under a second
CHANGE = fx.CHANGE
PIN_COMMIT = 'c' * 40
BUILDER_SHA = hashlib.sha256(b'synthetic builder agent/Skill manifest').hexdigest()
REVIEWER_SHA = hashlib.sha256(b'synthetic reviewer agent/Skill manifest').hexdigest()


REVISION = b'\nRevised after review.\n'
REVISION_MESSAGE, REVISION_DATE = 'Revise the design', '2026-11-07T01:00:00Z'


def _build_revised_design(repo):
    commit = fx.build_repo(repo)
    design_md = repo / 'openspec' / 'changes' / CHANGE / 'design.md'
    design_md.write_bytes(design_md.read_bytes() + REVISION)
    return commit, fx.commit_all(repo, REVISION_MESSAGE, date=REVISION_DATE)


def build_revised_design(repo):
    """(first, second) commits of the design repository with a later design revision (design.md
    changed in a second commit): built once per process per input digest and copied
    (two_task_fixture.golden, plan leaf F-09.3)."""
    key = fx.input_digest('dispatch-revised-design/1', fx.design_files(), fx.DESIGN_MESSAGE, fx.GIT_ENV,
                          REVISION, REVISION_MESSAGE, REVISION_DATE)
    return fx.golden(repo, key, _build_revised_design)


def rmtree(path):
    def retry(func, target, _exc):
        os.chmod(target, stat.S_IWRITE)
        func(target)
    shutil.rmtree(path, onexc=retry)


# The checked-in create template and route allowlist of the strong Windows profile (byte-exact by
# profiles/.gitattributes), copied beside every synthetic profile and pinned by its declaration.
AGENT_SERVER = REPO / 'profiles' / 'strong-windows-qemu-whpx' / 'agent-server'
TEMPLATE_BYTES = (AGENT_SERVER / 'conversation-create.json').read_bytes()
ROUTES_BYTES = (AGENT_SERVER / 'routes.json').read_bytes()


def admission_declaration(name, template=TEMPLATE_BYTES, routes=ROUTES_BYTES):
    """The parts of a profile declaration the E-01.2.2 admission reads, with the strong Windows
    profile's values (ceilings, Agent Server configuration, conversation mounts, pinned artifacts)."""
    base = f'profiles/{name}/agent-server'
    hexed = '{conversation_hex}'
    return {
        'ceilings': {'vcpu': 8, 'memory_mib': 16384, 'root_disk_gib': 40, 'scratch_disk_gib': 120},
        'provisioning': {'agent_server': {
            'config': {'content': {
                'conversation_runtime': 'docker', 'conversation_runtime_selectable': False,
                'conversation_container_memory': '4g', 'conversation_container_cpus': 2.0,
                'conversation_container_pids_limit': 512, 'max_concurrent_runs': 3}},
            'fixture': {'path': f'{base}/conversation-create.json', 'sha256': hashlib.sha256(template).hexdigest()},
            'conversations': {
                'source_root': '/srv/scratch/openhands',
                'mounts': [
                    {'type': 'bind', 'source': f'/srv/scratch/openhands/conversations/{hexed}',
                     'destination': f'/var/openhands/conversations/{hexed}', 'rw': True},
                    {'type': 'bind', 'source': f'/srv/scratch/openhands/persistence/runtime-data/{hexed}/persistence',
                     'destination': '/var/openhands/.openhands', 'rw': True},
                    {'type': 'bind', 'source': f'/srv/scratch/openhands/persistence/runtime-data/{hexed}/workspace',
                     'destination': '/workspace', 'rw': True}],
                'forbidden_sources': ['/run/docker.sock', '/var/run/docker.sock', '/run/containerd', '/run/docker',
                                      '/srv/scratch/docker', '/etc/aieh', '/var/lib/aieh', '/etc', '/root', '/home',
                                      '/proc', '/sys', '/dev', '/run', '/var/run']},
            'admission': {'routes': {'path': f'{base}/routes.json', 'sha256': hashlib.sha256(routes).hexdigest()}}}},
    }


def profile_bytes(name, operational=True, schema=di.PROFILE_SCHEMA, template=TEMPLATE_BYTES, routes=ROUTES_BYTES):
    declared = {'schema': schema, 'name': name, 'labels': {'tier': 'strong'}, 'status': {'operational': operational}}
    declared.update(admission_declaration(name, template, routes))
    return (json.dumps(declared, indent=2) + '\n').encode('utf-8')


def write_agent_server(profile_dir, template=TEMPLATE_BYTES, routes=ROUTES_BYTES):
    (profile_dir / 'agent-server').mkdir(parents=True, exist_ok=True)
    (profile_dir / 'agent-server' / 'conversation-create.json').write_bytes(template)
    (profile_dir / 'agent-server' / 'routes.json').write_bytes(routes)


class SnapshotBacklog:
    """Backlog.md's recorded readiness output, replayed in process (task list and task view).

    ``references`` overrides a task's references, as Backlog.md would report them after an edit.
    """

    def __init__(self, stage, references=None, fail=False):
        self.stage = READINESS / stage
        self.references = references or {}
        self.fail = fail
        self.calls = []

    def _envelope(self, name, kind):
        data = json.loads((self.stage / name).read_text(encoding='utf-8'))
        assert data['schemaVersion'] == 1 and data['kind'] == kind
        return data

    def list_tasks(self):
        self.calls.append(('task', 'list'))
        if self.fail:
            raise planning.PlanningError('BACKLOG_FAILED', 'backlog task list exited 1')
        return self._envelope('task-list.json', 'task-list')['tasks']

    def view(self, task_id):
        self.calls.append(('task', 'view', task_id))
        path = self.stage / f'task-view-{task_id.upper()}.json'
        if not path.is_file():
            raise planning.PlanningError('BACKLOG_FAILED', f'Task {task_id} not found.')
        task = self._envelope(path.name, 'task-view')['task']
        if task['id'] in self.references:
            task['references'] = list(self.references[task['id']])
        return task


class CountingSource:
    def __init__(self, inner):
        self.inner, self.reads = inner, 0

    def read(self, work_id):
        self.reads += 1
        return self.inner.read(work_id)


class Fixture(unittest.TestCase):
    """A design repository, profiles, a manifest file and an integration store, all under TEMP."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='aieh-dispatch-'))
        cls.design_repo = cls.tmp / 'design'
        cls.commit, cls.commit2 = build_revised_design(cls.design_repo)
        cls.git = planning.Git(cls.design_repo)
        cls.pointer2 = planning.make_pointer(cls.git, CHANGE, 'design.md', cls.commit2).text
        cls.profiles = cls.tmp / 'profiles'
        for name, operational in (('strong-test-profile', True), ('strong-dormant', False),
                                  ('strong-unbound', True)):
            (cls.profiles / name).mkdir(parents=True)
            (cls.profiles / name / 'profile.json').write_bytes(profile_bytes(name, operational))
            write_agent_server(cls.profiles / name)

    @classmethod
    def tearDownClass(cls):
        rmtree(cls.tmp)

    def setUp(self):
        self.case = Path(tempfile.mkdtemp(prefix='case-', dir=self.tmp))
        self.store = store_mod.open_store(self.case / 'integration.sqlite')
        self.addCleanup(self.store.close)
        self.ordinal_calls = []
        self.sources = {'demo-app': CountingSource(di.PlanningWorkSource(SnapshotBacklog('unblocked'), self.git))}
        # One git read session per test (plan leaf F-09.4): the test's dispatch reads share one
        # batch reader. The design repository never changes during a test, and the session (with
        # its memo) ends with the test, so nothing is kept for the next one.
        self.enterContext(self.git.session())

    # -- builders -------------------------------------------------------

    def profile_sha(self, name):
        return hashlib.sha256((self.profiles / name / 'profile.json').read_bytes()).hexdigest()

    def manifest_data(self):
        return {
            'schema': di.MANIFEST_SCHEMA, 'version': 7,
            'repositories': [{'id': 'demo-app'}, {'id': 'other-app'}],
            'designs': [{'repository': 'demo-app', 'change': CHANGE, 'commit': self.commit}],
            'profiles': [{'id': name, 'sha256': self.profile_sha(name)}
                         for name in ('strong-test-profile', 'strong-dormant', 'strong-unbound')],
            'catalog_pins': [
                {'id': 'builder-pin', 'repository': 'aieh-catalog', 'commit': PIN_COMMIT,
                 'manifest_sha256': BUILDER_SHA},
                {'id': 'reviewer-pin', 'repository': 'aieh-catalog', 'commit': PIN_COMMIT,
                 'manifest_sha256': REVIEWER_SHA}],
            'bindings': [
                {'repository': 'demo-app', 'stage': 'implement',
                 'profiles': ['strong-test-profile', 'strong-dormant'], 'catalog_pins': ['builder-pin']},
                {'repository': 'other-app', 'stage': 'review', 'profiles': ['strong-test-profile'],
                 'catalog_pins': ['reviewer-pin']}],
        }

    def write_manifest(self, data, name='approved-inputs.json'):
        path = self.case / name
        path.write_bytes(json.dumps(data, indent=2).encode('utf-8'))
        return di.load_manifest(path)

    def request(self, **changes):
        request = {'format': di.REQUEST_FORMAT, 'work_id': 'TASK-2', 'repository': 'demo-app',
                   'stage': 'implement', 'profile': 'strong-test-profile', 'catalog_pin': 'builder-pin'}
        request.update(changes)
        return request

    def next_ordinal(self, *args):
        self.ordinal_calls.append(args)
        return di.store_next_ordinal(self.store)(*args)

    def resolve(self, request=None, manifest=None, sources=None):
        manifest = manifest or self.write_manifest(self.manifest_data())
        sources = self.sources if sources is None else sources
        return di.resolve(self.request() if request is None else request, manifest=manifest,
                          work_sources=sources.get, next_ordinal=self.next_ordinal,
                          read_profile=lambda name: di.read_profile_file(name, profiles_root=self.profiles))

    def assertRefused(self, code, request=None, manifest=None, sources=None):
        with self.assertRaises(di.DispatchRefused) as caught:
            self.resolve(request, manifest, sources)
        self.assertEqual(caught.exception.code, code, caught.exception.detail)
        self.assertIn(code, di.REFUSALS)
        self.assertEqual(caught.exception.to_json()['code'], code)
        # Before any reservation: nothing in the store and no ordinal asked for.
        self.assertEqual(self.store.attempts(), [])
        self.assertEqual(self.ordinal_calls, [])
        return caught.exception

    def source_with(self, stage='unblocked', references=None, fail=False):
        return {'demo-app': CountingSource(di.PlanningWorkSource(
            SnapshotBacklog(stage, references=references, fail=fail), self.git))}

    def task2_references(self):
        view = json.loads((READINESS / 'unblocked' / 'task-view-TASK-2.json').read_text(encoding='utf-8'))
        return view['task']['references']


class AcceptanceRefusalTests(Fixture):
    """The E-01.2.1 proof: unapproved source or agent revisions are refused before provisioning."""

    def test_unapproved_repository(self):
        self.assertRefused('REPOSITORY_NOT_APPROVED', self.request(repository='unknown-app'))
        self.assertEqual(self.sources['demo-app'].reads, 0)

    def test_design_revision_other_than_the_accepted_one(self):
        data = self.manifest_data()
        data['designs'][0]['commit'] = self.commit2
        refusal = self.assertRefused('DESIGN_REVISION_MISMATCH', manifest=self.write_manifest(data))
        self.assertEqual((refusal.context['pinned'], refusal.context['accepted']), (self.commit, self.commit2))

    def test_task_pinning_a_later_unaccepted_revision(self):
        refs = [planning.make_pointer(self.git, CHANGE, 'design.md', self.commit2).text]
        self.assertRefused('DESIGN_REVISION_MISMATCH', sources=self.source_with(references={'TASK-2': refs}))

    def test_change_without_an_accepted_revision(self):
        data = self.manifest_data()
        data['designs'] = []
        self.assertRefused('DESIGN_NOT_ACCEPTED', manifest=self.write_manifest(data))
        data['designs'] = [{'repository': 'other-app', 'change': CHANGE, 'commit': self.commit}]
        self.assertRefused('DESIGN_NOT_ACCEPTED', manifest=self.write_manifest(data, 'm2.json'))

    def test_unresolvable_design(self):
        good = self.task2_references()
        cases = {
            'digest mismatch': [good[0][:-1] + ('0' if good[0][-1] != '0' else '1')],
            'revision missing': [good[0].replace(self.commit, '0' * 40)],
            'artifact missing': [good[0].replace('/design.md@', '/absent.md@')],
        }
        for name, refs in cases.items():
            with self.subTest(name):
                refusal = self.assertRefused('DESIGN_UNRESOLVED', sources=self.source_with(references={'TASK-2': refs}))
                self.assertTrue(all(code.startswith('POINTER_') for code in refusal.context['codes']))

    def test_design_pointer_absent(self):
        self.assertRefused('DESIGN_POINTER_ABSENT',
                           sources=self.source_with(references={'TASK-2': ['https://example.invalid/x']}))
        self.assertRefused('DESIGN_POINTER_ABSENT', sources=self.source_with(references={'TASK-2': []}))

    def test_several_revisions_are_ambiguous(self):
        refs = self.task2_references() + [self.pointer2]
        self.assertRefused('DESIGN_AMBIGUOUS', sources=self.source_with(references={'TASK-2': refs}))

    def test_unapproved_profile(self):
        self.assertRefused('PROFILE_NOT_APPROVED', self.request(profile='strong-other'))

    def test_profile_not_bound_to_repository_and_stage(self):
        self.assertRefused('PROFILE_NOT_BOUND', self.request(profile='strong-unbound'))

    def test_drifted_profile(self):
        manifest = self.write_manifest(self.manifest_data())
        target = self.profiles / 'strong-test-profile' / 'profile.json'
        original = target.read_bytes()
        self.addCleanup(target.write_bytes, original)
        for name, changed in (('content', original.replace(b'"strong"', b'"trusted-workload"')),
                              ('line endings', original.replace(b'\n', b'\r\n')),
                              ('one byte appended', original + b' ')):
            with self.subTest(name):
                target.write_bytes(changed)
                refusal = self.assertRefused('PROFILE_DRIFTED', manifest=manifest)
                self.assertEqual(refusal.context['actual'], hashlib.sha256(changed).hexdigest())
        self.assertEqual(self.sources['demo-app'].reads, 0)

    def test_profile_missing_invalid_or_not_operational(self):
        self.assertRefused('PROFILE_NOT_OPERATIONAL', self.request(profile='strong-dormant'))
        data = self.manifest_data()
        data['profiles'][0]['sha256'] = hashlib.sha256(b'').hexdigest()
        target = self.profiles / 'strong-test-profile' / 'profile.json'
        original = target.read_bytes()
        self.addCleanup(target.write_bytes, original)
        for name, content, code in (
                ('renamed', profile_bytes('strong-imposter'), 'PROFILE_INVALID'),
                ('other schema', profile_bytes('strong-test-profile', schema='x/v1'), 'PROFILE_INVALID'),
                ('not JSON', b'\xff\xfe', 'PROFILE_INVALID'),
                ('duplicate key', b'{"name": "a", "name": "strong-test-profile"}', 'PROFILE_INVALID'),
                ('operational absent', json.dumps({'schema': di.PROFILE_SCHEMA,
                                                   'name': 'strong-test-profile'}).encode(), 'PROFILE_NOT_OPERATIONAL'),
                ('operational truthy string', profile_bytes('strong-test-profile', operational='yes'),
                 'PROFILE_NOT_OPERATIONAL')):
            with self.subTest(name):
                target.write_bytes(content)
                data['profiles'][0]['sha256'] = hashlib.sha256(content).hexdigest()
                self.assertRefused(code, manifest=self.write_manifest(data, f'{code}.json'))
        target.unlink()
        self.assertRefused('PROFILE_MISSING', manifest=self.write_manifest(data, 'missing.json'))

    def test_unknown_or_unbound_catalog_pin(self):
        self.assertRefused('CATALOG_PIN_UNKNOWN', self.request(catalog_pin='unknown-pin'))
        self.assertRefused('CATALOG_PIN_NOT_BOUND', self.request(catalog_pin='reviewer-pin'))

    def test_missing_catalog_pin(self):
        request = self.request()
        del request['catalog_pin']
        self.assertRefused('CATALOG_PIN_REQUIRED', request)
        self.assertRefused('CATALOG_PIN_REQUIRED', self.request(catalog_pin=None))
        self.assertRefused('CATALOG_PIN_REQUIRED', self.request(catalog_pin=''))

    def test_no_approved_catalog_refuses_every_admission(self):
        """Dispatch stays impossible until A-01.1 promotes approved pins: intended."""
        data = self.manifest_data()
        data['catalog_pins'] = []
        for binding in data['bindings']:
            binding['catalog_pins'] = []
        manifest = self.write_manifest(data)
        for pin in ('builder-pin', 'any-pin'):
            with self.subTest(pin):
                self.assertRefused('NO_APPROVED_CATALOG', self.request(catalog_pin=pin), manifest=manifest)

    def test_unknown_or_unbound_stage(self):
        self.assertRefused('STAGE_UNKNOWN', self.request(stage='deploy'))
        self.assertRefused('STAGE_NOT_BOUND', self.request(stage='review'))
        self.assertRefused('STAGE_NOT_BOUND', self.request(repository='other-app', stage='implement'))

    def test_work_not_ready(self):
        cases = (('blocked', 'TASK-2', 'BLOCKED_BY_DEPENDENCIES'),
                 ('missing', 'TASK-3', 'MISSING_DEPENDENCIES'),
                 ('unblocked', 'TASK-1', 'NOT_READY'))
        for stage, task, reason in cases:
            with self.subTest(stage=stage, task=task):
                refusal = self.assertRefused('WORK_NOT_READY', self.request(work_id=task),
                                             sources=self.source_with(stage))
                self.assertIn(reason, refusal.context['reasons'])

    def test_work_readiness_is_decided_before_the_design(self):
        broken = [self.task2_references()[0].replace(self.commit, '0' * 40)]
        refusal = self.assertRefused('WORK_NOT_READY',
                                     sources=self.source_with('blocked', references={'TASK-2': broken}))
        self.assertEqual(refusal.context['reasons'], ['BLOCKED_BY_DEPENDENCIES'])

    def test_readiness_entry_that_is_not_eligible_fails_closed(self):
        inner = di.PlanningWorkSource(SnapshotBacklog('unblocked'), self.git)

        class NotEligible:
            def read(self, work_id):
                return dict(inner.read(work_id), eligible=False)

        class NoReasons:
            def read(self, work_id):
                return {key: value for key, value in inner.read(work_id).items() if key != 'reasons'}

        self.assertRefused('WORK_NOT_READY', sources={'demo-app': NotEligible()})
        self.assertRefused('WORK_UNREADABLE', sources={'demo-app': NoReasons()})

    def test_work_unknown_or_unreadable(self):
        self.assertRefused('WORK_NOT_FOUND', self.request(work_id='TASK-9'))
        refusal = self.assertRefused('WORK_UNREADABLE', sources=self.source_with(fail=True))
        self.assertEqual(refusal.context['planning_code'], 'BACKLOG_FAILED')
        self.assertRefused('WORK_SOURCE_UNAVAILABLE', sources={})

    def test_extra_or_unknown_request_field(self):
        for field in ('note', 'priority', 'extra', 'Work_Id'):
            with self.subTest(field):
                refusal = self.assertRefused('REQUEST_UNKNOWN_FIELD', self.request(**{field: 'x'}))
                self.assertEqual(refusal.context['fields'], [field])

    def test_caller_supplied_path_digest_or_runtime_fields(self):
        fields = {
            'working_dir': 'D:/work/repo', 'workspace': {'kind': 'LocalWorkspace'},
            'planned_workspace': 'demo-app/TASK-2/x', 'mounts': ['/:/host'], 'volumes': [],
            'profile_digest': '0' * 64, 'policy_digest': '0' * 64, 'agent_manifest_digest': '0' * 64,
            'design_revision': f'openspec:changes/{CHANGE}@{"0" * 40}', 'commit': '0' * 40,
            'conversation_runtime': 'local', 'runtime': 'process', 'image': 'agent-server:latest',
            'cpu': 64, 'memory_mb': 65536, 'network': 'host', 'env': {'X': '1'}, 'ordinal': 7,
            'conversation_id': '00000000-0000-0000-0000-000000000000'}
        for field, value in fields.items():
            with self.subTest(field):
                refusal = self.assertRefused('REQUEST_OVERRIDE_FORBIDDEN', self.request(**{field: value}))
                self.assertEqual(refusal.context['fields'], [field])

    def test_identifier_fields_take_no_paths(self):
        cases = {
            'repository': ['C:\\src\\demo-app', '../demo-app', 'demo-app/../x', '/srv/demo-app', 'Demo-App',
                           'demo_app', 'a' * 65, 7, None],
            'profile': ['../strong-test-profile', 'strong-test-profile/..', 'profiles/strong-test-profile',
                        'strong-test-profile.json', ''],
            'stage': ['implement/../review', 'IMPLEMENT', ''],
            'work_id': ['TASK-2\n', 'TASK-2/..', '../TASK-2', 'TASK', 2, 'T-' + '1' * 63],
            'catalog_pin': ['../builder-pin', 'builder-pin@' + 'c' * 40, 5],
        }
        for field, values in cases.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    refusal = self.assertRefused('REQUEST_FIELD_INVALID', self.request(**{field: value}))
                    self.assertEqual(refusal.context['field'], field)

    def test_malformed_request(self):
        no_work = self.request()
        del no_work['work_id']
        for name, request in (('not an object', ['TASK-2']), ('no format', {k: v for k, v in self.request().items()
                                                                             if k != 'format'}),
                              ('other format', self.request(format='ai-engineering-harness/dispatch/request/v2')),
                              ('missing work', no_work), ('non-string key', {**self.request(), 1: 'x'})):
            with self.subTest(name):
                self.assertRefused('REQUEST_MALFORMED', request)


class SuccessTests(Fixture):
    def test_resolved_record_reserves(self):
        record = self.resolve()
        identity = record.attempt_identity()
        key = identity.operation_key
        attempt_id = store_mod.attempt_id_for(key)
        self.assertEqual(record.design_revision, f'openspec:changes/{CHANGE}@{self.commit}')
        self.assertEqual(record.profile_digest, self.profile_sha('strong-test-profile'))
        self.assertEqual(record.agent_manifest_digest, BUILDER_SHA)
        self.assertEqual(record.planned_workspace, f'demo-app/TASK-2/{attempt_id}')
        self.assertEqual((record.work_id, record.stage, record.ordinal), ('TASK-2', 'implement', 1))
        self.assertEqual(record.manifest_version, 7)
        self.assertEqual(self.ordinal_calls, [('TASK-2', record.design_revision, 'implement')])

        result = self.store.reserve_attempt(identity, record.intent(), actor='dispatch-test')
        self.assertTrue(result.created)
        self.assertEqual(result.attempt.identity, identity)
        self.assertEqual(result.attempt.attempt_id, attempt_id)
        stored = json.loads(result.reservation.intent_json)
        self.assertEqual(stored[di.INTENT_KEY]['approval'],
                         {'manifest_schema': di.MANIFEST_SCHEMA, 'manifest_version': 7,
                          'manifest_sha256': record.manifest_sha256})
        self.assertEqual(stored[di.INTENT_KEY]['policy_digest'], record.policy_digest)
        self.assertEqual(stored['workRef'], 'backlog:TASK-2')
        # The same record again is idempotent.
        self.assertFalse(self.store.reserve_attempt(identity, record.intent(), actor='dispatch-test').created)

        # The next resolution asks for ordinal 2 with its own workspace; the store, not the
        # resolver, arbitrates the live claim, and admits it once the first attempt failed.
        second = self.resolve()
        self.assertEqual(second.ordinal, 2)
        self.assertNotEqual(second.planned_workspace, record.planned_workspace)
        with self.assertRaises(store_mod.LiveClaim):
            self.store.reserve_attempt(second.attempt_identity(), second.intent(), actor='dispatch-test')
        self.store.transition(key, 'failed', actor='dispatch-test', reason='test')
        self.assertTrue(self.store.reserve_attempt(second.attempt_identity(), second.intent(),
                                                   actor='dispatch-test').created)

    def test_review_stage_on_another_binding(self):
        sources = {'other-app': self.sources['demo-app']}
        data = self.manifest_data()
        data['designs'].append({'repository': 'other-app', 'change': CHANGE, 'commit': self.commit})
        record = self.resolve(self.request(repository='other-app', stage='review', catalog_pin='reviewer-pin'),
                              self.write_manifest(data), sources)
        self.assertEqual((record.stage, record.agent_manifest_digest), ('review', REVIEWER_SHA))
        self.assertTrue(record.planned_workspace.startswith('other-app/TASK-2/'))

    def test_work_id_case_is_canonical(self):
        self.assertEqual(self.resolve(self.request(work_id='task-2')), self.resolve())

    def test_today_s_real_profiles_are_refused(self):
        """The checked-in profiles declare operational false (C6): approving their exact bytes
        still does not admit them."""
        for name in ('strong-windows-qemu-whpx', 'strong-incus-vm'):
            with self.subTest(name):
                raw = di.read_profile_file(name)
                data = self.manifest_data()
                data['profiles'].append({'id': name, 'sha256': hashlib.sha256(raw).hexdigest()})
                data['bindings'][0]['profiles'].append(name)
                with self.assertRaises(di.DispatchRefused) as caught:
                    di.resolve(self.request(profile=name), manifest=self.write_manifest(data, f'{name}.json'),
                               work_sources=self.sources.get, next_ordinal=self.next_ordinal)
                self.assertEqual(caught.exception.code, 'PROFILE_NOT_OPERATIONAL')
        with self.assertRaises(ValueError):
            di.read_profile_file('../strong-incus-vm')


class DeterminismTests(Fixture):
    def test_same_inputs_give_an_identical_record(self):
        manifest = self.write_manifest(self.manifest_data())
        first, second = self.resolve(manifest=manifest), self.resolve(manifest=manifest)
        self.assertEqual(first, second)
        self.assertEqual(di._canonical(first.to_json()), di._canonical(second.to_json()))
        self.assertEqual(store_mod.intent_digest(first.intent()), store_mod.intent_digest(second.intent()))

    def test_policy_digest_is_pinned(self):
        record = self.resolve()
        self.assertEqual(record.policy_inputs, {
            'format': di.POLICY_FORMAT, 'repository': {'id': 'demo-app'}, 'stage': 'implement',
            'design': {'repository': 'demo-app', 'change': CHANGE, 'commit': self.commit},
            'profile': {'id': 'strong-test-profile', 'sha256': self.profile_sha('strong-test-profile')},
            'catalog_pin': {'id': 'builder-pin', 'repository': 'aieh-catalog', 'commit': PIN_COMMIT,
                            'manifest_sha256': BUILDER_SHA},
            'admission': expected_admission('strong-test-profile')})
        self.assertEqual(record.policy_digest,
                         hashlib.sha256(di._canonical(record.policy_inputs).encode('utf-8')).hexdigest())
        # The canonical serialization: sorted keys, no whitespace.
        self.assertEqual(record.policy_inputs_json, json.dumps(record.policy_inputs, sort_keys=True,
                                                               separators=(',', ':'), ensure_ascii=False))
        self.assertEqual(self.commit, '8eacfa81953a9129f3a8ee4c943f3030fd1c4fb7')
        self.assertEqual(record.policy_digest, GOLDEN_POLICY_DIGEST)

    def test_each_policy_input_changes_the_digest(self):
        base = (dict(id='demo-app'), 'implement',
                dict(repository='demo-app', change=CHANGE, commit=self.commit),
                dict(id='strong-test-profile', sha256='a' * 64),
                dict(id='builder-pin', repository='aieh-catalog', commit=PIN_COMMIT, manifest_sha256=BUILDER_SHA),
                expected_admission('strong-test-profile'))
        digest = di._sha256(di._canonical(di.policy_inputs(*base)))
        variants = []
        for position, key, value in ((0, 'id', 'other-app'), (2, 'commit', 'b' * 40), (2, 'change', 'other'),
                                     (3, 'sha256', 'b' * 64), (3, 'id', 'strong-x'), (4, 'commit', 'd' * 40),
                                     (4, 'manifest_sha256', REVIEWER_SHA), (4, 'repository', 'x'),
                                     (4, 'id', 'other-pin'), (5, 'caps', {'memory': '2g'}),
                                     (5, 'ceilings', {'vcpu': 16}), (5, 'create_template', {'sha256': 'b' * 64}),
                                     (5, 'routes', {'sha256': 'b' * 64}), (5, 'mounts', {'source_root': '/srv'})):
            changed = copy.deepcopy(list(base))
            if isinstance(value, dict):
                changed[position][key].update(value)
            else:
                changed[position][key] = value
            variants.append(di._sha256(di._canonical(di.policy_inputs(*changed))))
        changed = list(base)
        changed[1] = 'review'
        variants.append(di._sha256(di._canonical(di.policy_inputs(*changed))))
        self.assertNotIn(digest, variants)
        self.assertEqual(len(set(variants)), len(variants))

    def test_manifest_revision_changes_provenance_not_policy(self):
        first = self.resolve()
        data = self.manifest_data()
        data['version'] = 8
        data['repositories'].append({'id': 'unrelated-app'})
        second = self.resolve(manifest=self.write_manifest(data, 'v8.json'))
        self.assertEqual(second.policy_digest, first.policy_digest)
        self.assertEqual(second.attempt_identity(), first.attempt_identity())
        self.assertNotEqual(second.manifest_sha256, first.manifest_sha256)
        self.assertEqual(second.manifest_version, 8)
        self.assertNotEqual(store_mod.intent_digest(second.intent()), store_mod.intent_digest(first.intent()))
        # So a retry of the same key under another approval is a conflict, never silently the same.
        self.store.reserve_attempt(first.attempt_identity(), first.intent(), actor='dispatch-test')
        with self.assertRaises(store_mod.ConflictingReservation):
            self.store.reserve_attempt(second.attempt_identity(), second.intent(), actor='dispatch-test')

    def test_record_is_immutable(self):
        record = self.resolve()
        with self.assertRaises(Exception):
            record.policy_digest = '0' * 64
        inputs = record.policy_inputs
        inputs['stage'] = 'review'
        self.assertEqual(record.policy_inputs['stage'], 'implement')


def expected_admission(name):
    """The admission policy (policy-inputs/v2) the synthetic declaration gives, spelled out."""
    declared = admission_declaration(name)
    server = declared['provisioning']['agent_server']
    return {'runtime': {'conversation_runtime': 'docker', 'selectable': False},
            'route': {'method': 'POST', 'path': '/api/conversations'},
            'routes': server['admission']['routes'], 'create_template': server['fixture'],
            'workspace': {'category': 'workspaces', 'working_dir': '/workspace'},
            'caps': {'memory': '4g', 'cpus': 2.0, 'pids_limit': 512, 'max_concurrent_runs': 3},
            'ceilings': {'vcpu': 8, 'memory_mib': 16384},
            'mounts': {'source_root': '/srv/scratch/openhands', 'binds': server['conversations']['mounts'],
                       'forbidden_sources': server['conversations']['forbidden_sources']}}


# policy-inputs/v2 of the fixture (demo-app, implement, qual-02-search-freshness@8eacfa81...,
# strong-test-profile, builder-pin, the admission policy of admission_declaration with the
# checked-in template and route allowlist). A change means the canonical form changed: NEVER
# update it without a new POLICY_FORMAT. (policy-inputs/v1, E-01.2.1, was 45eeaeaf...e90b.)
GOLDEN_POLICY_DIGEST = '10ba1b157d89011ec93696be0dd8190697bc06244cfbeaeeb0623a984fb8a9d4'


def valid_manifest():
    return json.loads(EXAMPLE.read_text(encoding='utf-8'))


class ManifestCheckerTests(unittest.TestCase):
    category = 'unit'

    def codes(self, data):
        return [code for code, _ in di.check_manifest(data)]

    def assertProblem(self, code, data):
        codes = self.codes(data)
        self.assertIn(code, codes)
        with self.assertRaises(di.DispatchRefused) as caught:
            di.parse_manifest(json.dumps(data).encode('utf-8'))
        self.assertEqual(caught.exception.code, 'MANIFEST_INVALID')
        self.assertIn(code, [p[0] for p in caught.exception.context['problems']])

    def test_example_is_valid(self):
        self.assertEqual(di.check_manifest(valid_manifest()), [])
        manifest = di.parse_manifest(EXAMPLE.read_bytes())
        self.assertEqual(manifest.version, 1)
        self.assertEqual(manifest.sha256, hashlib.sha256(EXAMPLE.read_bytes()).hexdigest())

    def mutate(self, edit):
        data = valid_manifest()
        edit(data)
        return data

    def test_schema(self):
        cases = {
            'not an object': [],
            'wrong schema': self.mutate(lambda d: d.update(schema='ai-engineering-harness/dispatch/approved-inputs/v2')),
            'unknown top key': self.mutate(lambda d: d.update(workspaces=[])),
            'missing section': self.mutate(lambda d: d.pop('bindings')),
            'section not a list': self.mutate(lambda d: d.update(profiles={})),
            'entry not an object': self.mutate(lambda d: d['repositories'].append('example-app')),
            'unknown entry key': self.mutate(lambda d: d['repositories'][0].update(path='D:/src/app')),
            'missing entry key': self.mutate(lambda d: d['catalog_pins'][0].pop('manifest_sha256')),
            'binding binds no profile': self.mutate(lambda d: d['bindings'][0].update(profiles=[])),
        }
        for name, data in cases.items():
            with self.subTest(name):
                self.assertProblem('MANIFEST_SCHEMA', data)
        for value in (0, -1, '1', 1.0, True, None):
            with self.subTest(version=value):
                self.assertProblem('MANIFEST_VERSION', self.mutate(lambda d: d.update(version=value)))

    def test_identifiers(self):
        cases = {
            'repository path': self.mutate(lambda d: d['repositories'][0].update(id='../app')),
            'profile upper case': self.mutate(lambda d: d['profiles'][0].update(id='Strong-X')),
            'design change': self.mutate(lambda d: d['designs'][0].update(change='Add_Search')),
            'binding list': self.mutate(lambda d: d['bindings'][0].update(profiles='strong-example-profile')),
            'binding list item': self.mutate(lambda d: d['bindings'][0].update(catalog_pins=[7])),
            'pin repository': self.mutate(lambda d: d['catalog_pins'][0].update(repository='')),
        }
        for name, data in cases.items():
            with self.subTest(name):
                self.assertProblem('MANIFEST_ID_INVALID', data)
        self.assertProblem('MANIFEST_STAGE_UNKNOWN', self.mutate(lambda d: d['bindings'][0].update(stage='deploy')))

    def test_duplicates(self):
        cases = {
            'repository': lambda d: d['repositories'].append({'id': 'example-app'}),
            'design per repository and change': lambda d: d['designs'].append(dict(d['designs'][0], commit='9' * 40)),
            'profile': lambda d: d['profiles'].append(dict(d['profiles'][0], sha256='9' * 64)),
            'catalog pin': lambda d: d['catalog_pins'].append(dict(d['catalog_pins'][1], id='example-builder-pin')),
            'binding per repository and stage': lambda d: d['bindings'].append(copy.deepcopy(d['bindings'][0])),
            'within a binding': lambda d: d['bindings'][0]['profiles'].append('strong-example-profile'),
        }
        for name, edit in cases.items():
            with self.subTest(name):
                self.assertProblem('MANIFEST_DUPLICATE', self.mutate(edit))
        raw = EXAMPLE.read_bytes().replace(b'"version": 1,', b'"version": 1, "version": 2,')
        with self.assertRaises(di.DispatchRefused) as caught:
            di.parse_manifest(raw)
        self.assertEqual((caught.exception.code, caught.exception.context['problems'][0][0]),
                         ('MANIFEST_INVALID', 'MANIFEST_JSON'))

    def test_unknown_references(self):
        cases = {
            'design repository': lambda d: d['designs'][0].update(repository='other-app'),
            'binding repository': lambda d: d['bindings'][0].update(repository='other-app'),
            'binding profile': lambda d: d['bindings'][0]['profiles'].append('strong-other'),
            'binding pin': lambda d: d['bindings'][1]['catalog_pins'].append('other-pin'),
        }
        for name, edit in cases.items():
            with self.subTest(name):
                self.assertProblem('MANIFEST_UNKNOWN_REFERENCE', self.mutate(edit))

    def test_non_full_commits(self):
        for value in ('1111111', '1' * 39, '1' * 41, 'A' * 40, 'g' * 40, 'main', 'HEAD', '1' * 63, 7, None):
            for section in ('designs', 'catalog_pins'):
                with self.subTest(section=section, commit=value):
                    self.assertProblem('MANIFEST_COMMIT_NOT_FULL',
                                       self.mutate(lambda d: d[section][0].update(commit=value)))
        for value in ('1' * 40, '1' * 64):
            self.assertEqual(self.codes(self.mutate(lambda d: d['designs'][0].update(commit=value))), [])

    def test_digest_format(self):
        for value in ('2' * 63, '2' * 65, 'A' * 64, 'sha256:' + '2' * 64, '', 5, None):
            for section, key in (('profiles', 'sha256'), ('catalog_pins', 'manifest_sha256')):
                with self.subTest(section=section, digest=value):
                    self.assertProblem('MANIFEST_DIGEST_INVALID',
                                       self.mutate(lambda d: d[section][0].update({key: value})))

    def test_unreadable_bytes(self):
        for raw in (b'\xff\xfe{}', b' ' * (di.MAX_MANIFEST_BYTES + 1)):
            with self.subTest(len(raw)):
                with self.assertRaises(di.DispatchRefused) as caught:
                    di.parse_manifest(raw)
                self.assertEqual(caught.exception.code, 'MANIFEST_UNREADABLE')
        with self.assertRaises(di.DispatchRefused) as caught:
            di.parse_manifest(b'{"schema": NaN}')
        self.assertEqual(caught.exception.code, 'MANIFEST_INVALID')

    def test_type_fuzzing_never_crashes(self):
        values = (None, 'x', 5, [], {}, [None], [5], {'a': 1}, True)
        base = valid_manifest()
        paths = [(k,) for k in base] + [(s, 0, k) for s in base if isinstance(base[s], list)
                                        for k in base[s][0]]
        for path in paths:
            for value in values:
                data = copy.deepcopy(base)
                target = data
                for part in path[:-1]:
                    target = target[part]
                target[path[-1]] = value
                with self.subTest(path=path, value=value):
                    problems = di.check_manifest(data)
                    self.assertIsInstance(problems, list)


class ManifestCustodyTests(unittest.TestCase):
    category = 'unit'

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-dispatch-custody-'))
        self.addCleanup(rmtree, self.tmp)

    def refused(self, path):
        with self.assertRaises(di.DispatchRefused) as caught:
            di.load_manifest(path)
        return caught.exception.code

    def test_live_manifest_never_in_the_checkout(self):
        self.assertEqual(self.refused(EXAMPLE), 'MANIFEST_INSIDE_CHECKOUT')
        self.assertEqual(self.refused(REPO), 'MANIFEST_INSIDE_CHECKOUT')
        self.assertEqual(self.refused(REPO.parent), 'MANIFEST_INSIDE_CHECKOUT')

    def test_path_shape(self):
        self.assertEqual(self.refused('approved-inputs.json'), 'MANIFEST_PATH_INVALID')
        self.assertEqual(self.refused(str(self.tmp / 'a' / '..' / 'm.json')), 'MANIFEST_PATH_INVALID')
        self.assertEqual(self.refused(None), 'MANIFEST_PATH_INVALID')
        self.assertEqual(self.refused(self.tmp / 'absent.json'), 'MANIFEST_MISSING')
        self.assertEqual(self.refused(self.tmp), 'MANIFEST_UNREADABLE')

    def test_loads_outside_the_checkout(self):
        path = self.tmp / 'approved-inputs.json'
        shutil.copyfile(EXAMPLE, path)
        manifest = di.load_manifest(path)
        self.assertEqual((manifest.version, manifest.sha256), (1, hashlib.sha256(path.read_bytes()).hexdigest()))
        path.write_bytes(path.read_bytes().replace(b'"version": 1', b'"version": 0'))
        self.assertEqual(self.refused(path), 'MANIFEST_INVALID')

    def test_manifest_path_is_in_the_managed_state_category(self):
        root = self.tmp / 'aieh-root'
        res = di.paths.resolve({'AIEH_DATA_ROOT': str(root)}, config={})
        self.assertEqual(di.manifest_path(res), root / 'persistent' / 'state' / 'dispatch' / 'approved-inputs.json')
        self.assertFalse(root.exists())  # computed, never created


class CliTests(unittest.TestCase):
    category = 'contract'

    def run_cli(self, *args, env=None):
        return subprocess.run([sys.executable, '-I', '-B', str(MODULE), *args], capture_output=True, text=True,
                              encoding='utf-8', timeout=WAIT_CEILING_S, stdin=subprocess.DEVNULL, cwd=REPO,
                              env=env)

    def test_check_manifest(self):
        ok = self.run_cli('check-manifest', '--manifest', str(EXAMPLE))
        self.assertEqual(ok.returncode, 0, ok.stderr)
        report = json.loads(ok.stdout)
        self.assertEqual((report['format'], report['version'], report['problems']), (di.CHECK_FORMAT, 1, []))
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp, 'bad.json')
            data = valid_manifest()
            data['designs'][0]['commit'] = 'abc1234'
            bad.write_text(json.dumps(data), encoding='utf-8')
            fail = self.run_cli('check-manifest', '--manifest', str(bad))
            self.assertEqual(fail.returncode, 1)
            self.assertIn('FAIL MANIFEST_COMMIT_NOT_FULL', fail.stderr)
            missing = self.run_cli('check-manifest', '--manifest', str(Path(tmp, 'absent.json')))
            self.assertEqual(missing.returncode, 2)

    def test_manifest_path_creates_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp, 'aieh-root')
            env = dict(os.environ, AIEH_DATA_ROOT=str(root))
            result = self.run_cli('manifest-path', env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(Path(result.stdout.strip()),
                             root / 'persistent' / 'state' / 'dispatch' / 'approved-inputs.json')
            self.assertFalse(root.exists())


if __name__ == '__main__':
    unittest.main()
