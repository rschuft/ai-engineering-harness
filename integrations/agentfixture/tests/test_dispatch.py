"""The proof of plan leaf E-01.8 (TASK-13): a ready task dispatched through the existing resolver and dispatcher on the
deterministic fixture transport, offline (the I1 integration design, slice 11; the engineering manager's rulings of
E-01.8).

The composition root (``integrations/agentfixture/run.py``) runs over:

- a throwaway integration store, and a throwaway project repository ``aieh-d1-demo``: D1's demo template, D1's
  design ``add-slugify`` placed and committed (the design commit), and one Backlog.md task file;
- a manifest made from the checked-in candidate (``integrations/dispatch/candidates/fixture-approved-inputs.json``,
  its design commit this repository's and its version the throwaway series' first) and promoted by the REAL recorder
  (``integrations/owner/input_recorder.py``) in a throwaway context (the dispatch-input commands' own fixtures:
  synthetic statements, a fixture harness repository), loaded with the real decision verifier;
- the checked-in fixture profile and the fixture pin's assignment (an in-memory catalog source holding the committed
  bytes at the pinned commit; ``PinnedCommit`` reads the assignment from git at that commit);
- the served fixture (``server.py`` in a thread, a free 127.0.0.1 port) over one core, reached through the fixture
  transport with its exchange delivery; the fixture's backend seams; and E-05.4's in-process Gitea fakes (imported
  from ``integrations/dispatch/tests/test_result_path.py``, unchanged) as the injected result target.

A create goes through the listener's validation, which needs the locked release openapi.json (never committed:
decision 0005): ``Dispatched`` runs when ``AIEH_LOCKED_OPENAPI`` names it and is skipped otherwise, saying so. The
refusals before anything (``BeforeAnything``), the delivery rule (``Delivery``) and the import census (``Census``) run
without it.
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import fixture_support as S

CATEGORY = 'integration'

REPO, PACKAGE = S.REPO, S.PACKAGE
RUN = S.load('agentfixture_run', PACKAGE / 'run.py')
backend = RUN.backend
di, AR, RP, RR, LG, NT = RUN.di, RUN.AR, RUN.RP, RUN.RR, RUN.LG, RUN.NT
store_mod = di.store
OWNER_TESTS = REPO / 'integrations' / 'owner' / 'tests'
sys.path.insert(0, str(OWNER_TESTS))
import input_fixture as fi  # noqa: E402
sys.path.insert(0, str(S.DISPATCH_TESTS))
import catalog_support as cs  # noqa: E402

DEMO = S.load('aieh_gitea_demo_repository', REPO / 'integrations' / 'gitea' / 'demo_repository.py')
CANDIDATE = REPO / 'integrations' / 'dispatch' / 'candidates' / 'fixture-approved-inputs.json'
NATIVE = REPO / 'profiles' / 'strong-windows-qemu-whpx'
OPENAPI = S.locked_openapi_path()
LOCKED = None if OPENAPI is None else S.SERVER.locked_document(OPENAPI)
REPOSITORY, CHANGE, WORK = 'aieh-d1-demo', 'add-slugify', 'TASK-1'
TITLE = 'Implement slugify(text) in aieh_d1_demo (add-slugify)'
OUTCOME = 'outcome:0d07308f-b43c-4907-91a4-170a16a77cbd'
# A synthetic, throwaway identity of the commissioning user (decision 0028: a provider-associated noreply address)
IDENTITY = 'E-01.8 Fixture Owner <e18-fixture-owner@users.noreply.github.com>'
TASK_VIEW = S.REPO / 'integrations' / 'planning' / 'tests' / 'fixtures' / 'readiness' / 'unblocked' / \
    'task-view-TASK-2.json'


def setUpModule():
    fi.start()


def tearDownModule():
    fi.stop()


def owner_host(project, identity=IDENTITY):
    raw = {'project_repository': str(project), 'project_repository_id': REPOSITORY, 'backlog_command': 'backlog'}
    if identity is not None:
        raw['git_identities'] = {'owner': identity}
    return raw


def make_project(path: Path) -> dict:
    """The throwaway aieh-d1-demo: C0 D1's demo template, C1 C0 and D1's design placed (the design commit), C2 one
    task file. The commit ids by name."""
    tar = S.load('test_attempt_run', S.DISPATCH_TESTS / 'test_attempt_run.py')
    c0 = DEMO.template_files()
    c1 = {**c0, **DEMO.design_files()}
    task = (f'---\nid: {WORK}\ntitle: \'{TITLE}\'\nstatus: To Do\n---\n\n## Description\n\n'
            'Implement the add-slugify change.\n').encode('utf-8')
    c2 = {**c1, f'backlog/tasks/{WORK.lower()} - Implement-slugify.md': task}
    return tar.make_repository(path, [('C0', c0), ('C1', c1), ('C2', c2)])


class Backlog:
    """Backlog.md's two read answers for the one task, replayed in process (the recorded task-view envelope of the
    planning fixtures, its task replaced): the task's source pointers at the design commit and its outcome."""

    def __init__(self, references):
        view = json.loads(TASK_VIEW.read_text(encoding='utf-8'))['task']
        self.task = {**view, 'id': WORK, 'title': TITLE, 'status': 'To Do', 'dependencies': [],
                     'references': references,
                     'path': f'backlog/tasks/{WORK.lower()} - Implement-slugify.md',
                     'dependencyGraph': {'root': WORK, 'nodes': [{'id': WORK, 'title': TITLE, 'status': 'To Do',
                                                                   'state': 'resolved', 'completed': False,
                                                                   'dependencyDepth': 0, 'dependentDepth': 0}],
                                         'edges': []}}

    def list_tasks(self):
        return [copy.deepcopy(self.task)]

    def view(self, task_id):
        return copy.deepcopy(self.task)


class Context(unittest.TestCase):
    """One throwaway context per test: the project, the store, the promoted manifest, the seams."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='e18-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.project = self.tmp / 'project'
        self.commits = make_project(self.project)
        self.design = self.commits['C1']
        (self.tmp / 'st').mkdir()
        self.store = store_mod.open_store(self.tmp / 'st' / 'integration.sqlite')
        self.addCleanup(self.store.close)
        self.workspaces = di.paths.resolve({'AIEH_DATA_ROOT': str(self.tmp / 'aieh-root')}, config={})
        self.catalog = cs.Catalog()
        self.catalog.entry_not_regular = di.CatalogEntryNotRegular
        candidate = json.loads(CANDIDATE.read_bytes())
        pin = candidate['catalog_pins'][0]
        self.catalog.put(pin['repository'], pin['commit'], {
            di.assignment_path(pin['id']): (REPO / di.assignment_path(pin['id'])).read_bytes(),
            cs.REGISTRY_PATH: cs.checked_in(cs.REGISTRY_PATH)})
        self.request = {'format': di.REQUEST_FORMAT, 'work_id': WORK, 'repository': REPOSITORY, 'stage': RUN.STAGE,
                        'profile': RUN.PROFILE, 'catalog_pin': RUN.CATALOG_PIN}

    # -- the manifest, promoted by the real recorder in a throwaway context ------------------------------------
    def promote(self) -> object:
        state, live = self.tmp / 'state', self.tmp / 'state' / 'dispatch' / 'approved-inputs.json'
        (state / 'dispatch').mkdir(parents=True)
        repos = fi._SHARED[-1][2]
        ctx = fi.IR.Context(state_root=state, store=self.store, manifest_path=live, harness=repos.harness['accepted'],
                            checkout=REPO, now=lambda: fi.NOW, replace=os.replace)
        challenge = fi.IR.design_prepare(ctx, self.project, REPOSITORY, CHANGE, self.design)
        fi.IR.design_record(ctx, challenge['shown']['nonce'], fi.statement(CHANGE), recorded_by=fi.RECORDED_BY)
        data = json.loads(CANDIDATE.read_bytes())
        data['version'] = 1                                          # the throwaway series' first position
        data['designs'][0]['commit'] = self.design                   # this throwaway repository's design commit
        path = self.tmp / 'candidate.json'
        path.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8', newline='\n')
        challenge = fi.IR.manifest_prepare(ctx, path)
        fi.IR.manifest_record(ctx, challenge['shown']['nonce'], fi.statement('approved-inputs-v1'),
                              recorded_by=fi.RECORDED_BY)
        return di.load_manifest(live, decisions=fi.I.verifier(self.store))

    def work_sources(self):
        git = di.planning.Git(self.project)
        pointers = []
        for name in ('proposal.md', 'design.md'):
            data = git.blob(self.design, f'openspec/changes/{CHANGE}/{name}') if hasattr(git, 'blob') else None
            if data is None:
                data = (self.project / 'openspec' / 'changes' / CHANGE / name).read_bytes()
            pointers.append(f'openspec:changes/{CHANGE}/{name}@{self.design}#sha256={hashlib.sha256(data).hexdigest()}')
        source = di.PlanningWorkSource(Backlog(pointers + [f'{OUTCOME}@{self.design}']), git)
        return {REPOSITORY: source}.get


class Counting:
    """A transport that must not be called (its calls are counted), declaring the fixture authority."""
    authority = 'fixture'

    def __init__(self):
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError('the transport was called')


class BeforeAnything(Context):
    """Step 0: the identity (capture's codes) and the target, refused before anything is read, called or written."""

    def refused(self, code, **changes):
        transport, credentials = Counting(), backend.FixtureCredentials()
        before = [(r.operation_key, r.state) for r in self.store.attempts()]
        kwargs = dict(owner_host=owner_host(self.project), integration_store=self.store, manifest=None,
                      work_sources=self.work_sources(), workspaces=self.workspaces, transport=transport, core=None,
                      credentials=credentials, pull=None, target=object())
        kwargs.update(changes)
        with self.assertRaises(RUN.RunRefused) as caught:
            RUN.run(self.request, **kwargs)
        self.assertEqual(caught.exception.code, code, caught.exception.detail)
        self.assertEqual((transport.calls, credentials.reads), (0, []), 'nothing called, no entry read')
        self.assertEqual([(r.operation_key, r.state) for r in self.store.attempts()], before, 'nothing written')
        return caught.exception

    def test_an_absent_or_invalid_identity_is_refused_with_captures_codes(self):
        self.refused('COMMIT_IDENTITY_UNAVAILABLE', owner_host=owner_host(self.project, identity=None))
        self.refused('COMMIT_IDENTITY_PLACEHOLDER', owner_host=owner_host(self.project, 'Bot <bot@localhost.invalid>'))
        self.refused('COMMIT_IDENTITY_INVALID', owner_host=owner_host(self.project, 'no address at all'))
        self.refused('CAPTURE_PROJECT_UNCONFIGURED', owner_host=None)

    def test_no_target_and_another_project_are_refused(self):
        self.refused('RESULT_TARGET_UNCONFIGURED', target=None)
        other = owner_host(self.project)
        other['project_repository_id'] = 'another-repository'
        self.refused('PROJECT_NOT_REQUESTED', owner_host=other)

    def test_recover_runs_first_and_a_busy_lock_or_a_held_row_stops_the_run(self):
        busy = di.DispatchRefused('DISPATCHER_BUSY', 'another dispatcher act holds the lock')
        with mock.patch.object(RUN.RR, 'recover', side_effect=busy) as recover:
            self.refused('DISPATCHER_BUSY')
        recover.assert_called_once()
        held = {'held': [{'operationKey': 'attempt/v1/x', 'code': 'OUTCOME_UNKNOWN'}], 'entries': []}
        with mock.patch.object(RUN.RR, 'recover', return_value=held):
            refusal = self.refused('OUTCOME_UNKNOWN')
        self.assertEqual(refusal.context['held'], [{'operationKey': 'attempt/v1/x', 'code': 'OUTCOME_UNKNOWN'}])

    def test_the_command_refuses_until_its_target_is_configured(self):
        out = subprocess.run([sys.executable, '-I', '-B', str(PACKAGE / 'run.py'), 'dispatch', '--work-id', WORK,
                              '--repository', REPOSITORY], capture_output=True, text=True, timeout=120,
                             creationflags=S.NO_WINDOW, cwd=self.tmp,
                             env={**os.environ, 'AIEH_DATA_ROOT': str(self.tmp / 'aieh-root')})
        self.assertEqual(out.returncode, 2, out.stderr)
        self.assertEqual(json.loads(out.stdout)['code'], 'RESULT_TARGET_UNCONFIGURED')


class Delivery(unittest.TestCase):
    """R13's delivery: tools/guest.py's own API_PROBE deliver, read as data and pinned."""
    category = 'unit'

    def test_the_rule_is_the_probes_own_and_its_shape_is_pinned(self):
        import ast
        source = (REPO / 'tools' / 'guest.py').read_text(encoding='utf-8')
        probe = next(ast.literal_eval(n.value) for n in ast.parse(source).body if isinstance(n, ast.Assign)
                     and [getattr(t, 'id', None) for t in n.targets] == ['API_PROBE'])
        node = next(n for n in ast.parse(probe).body if isinstance(n, ast.FunctionDef) and n.name == 'deliver')
        text = ast.get_source_segment(probe, node)
        self.assertEqual(hashlib.sha256(text.encode('utf-8')).hexdigest(), PINNED_DELIVER_SHA256,
                         'tools/guest.py API_PROBE deliver changed shape: review the fixture delivery against it')
        deliver, limit = S.TRANSPORT.pinned_delivery()
        self.assertEqual(deliver.__code__.co_filename.endswith('API_PROBE'), True)
        self.assertEqual(limit, 12 << 20)

    def test_it_answers_as_the_tests_mirror_of_the_probe(self):
        tar = S.load('test_attempt_run', S.DISPATCH_TESTS / 'test_attempt_run.py')
        data = b'bundle bytes \x00\x01'
        digest = hashlib.sha256(data).hexdigest()
        stdout = (f'AIEH-RESULT done\nAIEH-EXCHANGE-PART bundle {digest} {len(data)}\n{data.hex()}\n'
                  'AIEH-EXCHANGE-END bundle\ntail\n')
        tmp = Path(tempfile.mkdtemp(prefix='e18d-'))
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / 'a').mkdir()
        (tmp / 'b').mkdir()
        deliver, _ = S.TRANSPORT.pinned_delivery()
        entry = {'body': {'stdout': stdout, 'exit_code': 0}}
        delivered = deliver({'field': 'stdout', 'part': 'bundle', 'name': 'x.bundle', 'dir': str(tmp / 'a'),
                             'name_pattern': '^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$', 'max_bytes': 1 << 20}, entry)
        mirror_stdout, mirrored = tar.deliver(stdout, tmp / 'b', 'x.bundle')
        self.assertEqual((entry['body']['stdout'], delivered), (mirror_stdout, mirrored))
        self.assertEqual((tmp / 'a' / 'x.bundle').read_bytes(), data)

    def test_without_an_exchange_a_delivery_is_refused_before_anything_is_sent(self):
        transport = S.TRANSPORT.FixtureTransport(UNUSED_PORT)
        with self.assertRaises(S.TRANSPORT.FixtureTransportError) as caught:
            transport('POST', '/x', {'command': 'c'}, deliver={'part': 'bundle', 'name': 'x.bundle'})
        self.assertEqual((caught.exception.code, transport.calls), ('FIXTURE_DELIVERY_UNAVAILABLE', []))

    def test_a_delivery_name_outside_the_grammar_is_refused_before_anything_is_sent(self):
        """The review's item 7: tools/guest.py's own check_exchange_name, applied before sending, as the live path
        (exchange_delivery) applies it."""
        tmp = Path(tempfile.mkdtemp(prefix='e18n-'))
        self.addCleanup(shutil.rmtree, tmp, True)
        bounds = json.loads((NATIVE / 'profile.json').read_bytes())['exchange']['pull']
        transport = S.TRANSPORT.FixtureTransport(UNUSED_PORT, exchange=tmp, bounds={
            k: bounds[k] for k in ('name_pattern', 'max_bytes')})
        for name in ('../x.bundle', 'x.bundle.partial', '.hidden', 'a/b'):
            with self.subTest(name=name):
                with self.assertRaises(S.TRANSPORT.FixtureTransportError) as caught:
                    transport('POST', '/x', {'command': 'c'}, deliver={'part': 'bundle', 'name': name})
                self.assertEqual((caught.exception.code, transport.calls), ('DELIVERY_INVALID', []))
        import ast
        source = (REPO / 'tools' / 'guest.py').read_text(encoding='utf-8')
        node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)
                    and n.name == 'check_exchange_name')
        self.assertEqual(hashlib.sha256(ast.get_source_segment(source, node).encode('utf-8')).hexdigest(),
                         PINNED_NAME_CHECK_SHA256, 'tools/guest.py check_exchange_name changed shape')


class Pull(unittest.TestCase):
    """The review's item 8: the fixture's pull stages a name exclusively; a second pull of it is refused."""
    category = 'integration'

    def test_a_second_pull_of_one_name_is_refused(self):
        tmp = Path(tempfile.mkdtemp(prefix='e18p-'))
        self.addCleanup(shutil.rmtree, tmp, True)
        for name in ('exchange', 'gstate', 'home'):
            (tmp / name).mkdir()
        (tmp / 'exchange' / 'x.bundle').write_bytes(b'not a bundle')
        with mock.patch.dict(os.environ, {'USERPROFILE': str(tmp / 'home'), 'HOME': str(tmp / 'home')}):
            puller = backend.Puller(tmp / 'exchange', tmp / 'gstate', NATIVE)
        with contextlib.suppress(Exception):      # the first pull stages it (its verification is not the point)
            puller('x.bundle')
        staged = backend.guest_module().staging_dir(puller.ctx, backend.INSTANCE, 'inbound') / 'x.bundle'
        self.assertEqual(staged.read_bytes(), b'not a bundle')
        with self.assertRaises(puller.guest.Refused) as caught:
            puller('x.bundle')
        self.assertIn('never overwritten', str(caught.exception))
        self.assertEqual(staged.read_bytes(), b'not a bundle')


# a port no request reaches: a delivery refused before anything is sent opens no socket (a unit class)
UNUSED_PORT = 9
# sha256 of tools/guest.py check_exchange_name's source text: a change of its shape fails Delivery
PINNED_NAME_CHECK_SHA256 = '9e89d46901ae56b3d16f057392e8f218698a2f9ec9678b282591da1deef8b6b6'
# sha256 of tools/guest.py API_PROBE's deliver function's source text: a change of its shape fails Delivery
PINNED_DELIVER_SHA256 = '083a466a2d661849676dbebccd7b898753445386ffa01fdf6222ca22a549b2a1'


class Census(unittest.TestCase):
    """The import census of the composition root (PB-3; R10). Found against the code: the production result path
    (result_path -> attempt_tokens -> gitea_roles -> gitea_host) binds integrations/credentials/credential_provider.py
    at its own import (gitea_host's module-level ``credentials = windows.credentials``), so the composition root
    loads that one module, and only it, from gitea_host; it loads no other credential module (not the native token
    entry command), no keyring, and constructs no provider. That nothing constructs the host credential provider
    during a run is ``Dispatched``'s construction census."""
    category = 'integration'

    def test_the_composition_root_loads_only_the_result_paths_bound_credential_module(self):
        script = ('import importlib.util, json, sys\n'
                  f'spec = importlib.util.spec_from_file_location("agentfixture_run", {str(PACKAGE / "run.py")!r})\n'
                  'module = importlib.util.module_from_spec(spec); sys.modules["agentfixture_run"] = module\n'
                  'spec.loader.exec_module(module)\n'
                  'module.capture_module()\n'
                  'host = sys.modules["aieh_gitea_host"]\n'
                  'files = sorted(str(getattr(m, "__file__", "") or "") for m in list(sys.modules.values()))\n'
                  'print(json.dumps({"bound": host.credentials is sys.modules.get("aieh_credential_provider"),\n'
                  '                  "files": files}))\n')
        out = subprocess.run([sys.executable, '-I', '-B', '-c', script], capture_output=True, text=True, timeout=120,
                             creationflags=S.NO_WINDOW)
        self.assertEqual(out.returncode, 0, out.stderr)
        found = json.loads(out.stdout)
        files = [Path(f) for f in found['files'] if f]
        credentials = REPO / 'integrations' / 'credentials'
        self.assertEqual([f.name for f in files if f.is_relative_to(credentials)], ['credential_provider.py'])
        self.assertTrue(found['bound'], 'loaded by gitea_host at its import, as its module-level binding')
        self.assertFalse(any('keyring' in f.parts for f in files))
        self.assertTrue(any(f.name == 'dispatch_inputs.py' for f in files))
        self.assertTrue(any(f.name == 'capture.py' for f in files))


class Audit:
    """What the run reaches of the host credential store: every ctypes library load and every import, recorded while
    armed (an audit hook cannot be removed: it is armed only around the run)."""
    armed = False
    events: list = []

    @classmethod
    def hook(cls, event, args):
        if cls.armed and event in ('ctypes.dlopen', 'import'):
            cls.events.append((event, str(args[0])))


sys.addaudithook(Audit.hook)


@unittest.skipIf(LOCKED is None, 'AIEH_LOCKED_OPENAPI is not given: a create through the listener needs the locked '
                                 'openapi.json, never committed (decision 0005)')
class Dispatched(Context):
    def setUp(self):
        super().setUp()
        self.manifest = self.promote()
        self.core = S.AC.AgentServerCore(scratch=self.tmp / 'core')
        self.addCleanup(self.core.close)
        self.listener = S.SERVER.Fixture('finished', core=self.core, openapi=LOCKED)
        self.served = S.InThread(self.listener).start()
        self.addCleanup(self.served.stop)
        bounds = json.loads((NATIVE / 'profile.json').read_bytes())['exchange']['pull']
        (self.tmp / 'exchange').mkdir()
        self.transport = S.TRANSPORT.FixtureTransport(self.served.port, timeout=300, exchange=self.tmp / 'exchange',
                                                      bounds={k: bounds[k] for k in ('name_pattern', 'max_bytes')})
        elsewhere = self.tmp / 'home'
        elsewhere.mkdir()
        (self.tmp / 'gstate').mkdir()
        with mock.patch.dict(os.environ, {'USERPROFILE': str(elsewhere), 'HOME': str(elsewhere)}):
            self.pull = backend.Puller(self.tmp / 'exchange', self.tmp / 'gstate', NATIVE)
        self.credentials = backend.FixtureCredentials()
        rp = S.load('test_result_path', S.DISPATCH_TESTS / 'test_result_path.py')
        self.remote = rp.DemoRemote(self.tmp, self.project, self.commits['C2'])
        self.addCleanup(self.remote.close)
        self.gitea = rp.DemoGitea(self.remote)
        self.target = RP.GiteaTarget(repository_id=REPOSITORY, full_name=rp.DEMO, port=rp.PORT,
                                     git_url=self.remote.url, http=self.gitea, authority='fixture')

    def run_composition(self, **changes):
        kwargs = dict(owner_host=owner_host(self.project), integration_store=self.store, manifest=self.manifest,
                      work_sources=self.work_sources(), workspaces=self.workspaces, transport=self.transport,
                      core=self.core, credentials=self.credentials, pull=self.pull, target=self.target,
                      catalog_sources=self.catalog.sources, report_dir=self.tmp / 'report')
        kwargs.update(changes)
        before = set(sys.modules)
        Audit.events.clear()
        provider = sys.modules['aieh_credential_provider']        # bound by gitea_host at the result path's import
        constructed = []

        def recorded(name, original):
            def record(*args, **kw):
                constructed.append(name)
                return original(*args, **kw)
            return record
        with contextlib.ExitStack() as stack:
            for name in ('select_provider', 'qualify_keyring'):
                stack.enter_context(mock.patch.object(provider, name, recorded(name, getattr(provider, name))))
            for name in ('CredentialStore', 'WindowsCredentialProvider', 'KeyringProvider'):
                cls = getattr(provider, name)
                stack.enter_context(mock.patch.object(cls, '__init__', recorded(name, cls.__init__)))
            Audit.armed = True
            try:
                summary = RUN.run(self.request, **kwargs)
            finally:
                Audit.armed = False
        self.constructed = constructed
        return summary, set(sys.modules) - before

    def test_the_ready_task_is_dispatched_once_through_the_production_path_and_every_record_is_fixture(self):
        summary, loaded = self.run_composition()
        key, attempt_id = summary['operationKey'], summary['attemptId']
        # dispatched exactly once on the fixture: one create, one SEED, one message, one RESULT
        self.assertEqual((summary['outcome'], summary['published']), ('verified', 'confirmed'))
        self.assertEqual(len(self.core.creates), 1)
        self.assertEqual(len(self.core.messages(summary['conversationId'])), 1)
        answers = [entry.get('answer') for entry in self.listener.log]
        self.assertEqual((answers.count('create-new'), answers.count('seed'), answers.count('message'),
                          answers.count('result')), (1, 1, 1, 1), answers)
        # the gate compared the fixture's cited recorded inspect, its logic unchanged
        launch = LG.launch_record(self.store, attempt_id)
        self.assertEqual((launch['verdict'], launch['inspect']['source'], launch['authority']),
                         (LG.LAUNCHED, RUN.SOURCE, 'fixture'))
        self.assertTrue(all(f['equal'] for f in launch['fields']))
        # the intake took the fixture's cited recorded result (D1's recorded test output, PB-4)
        intake = json.loads(self.store.get(AR.INTAKE_KEY.format(attempt_id=attempt_id)).intent_json)
        self.assertEqual(intake['record']['tests']['output']['sha256'], S.RESULT.TEST_OUTPUT_SHA256)
        delivered = json.loads(self.store.get(AR.DELIVERY_KEY.format(attempt_id=attempt_id)).intent_json)
        self.assertEqual(delivered['bundle']['sha256'], intake['record']['bundle']['sha256'])
        # the resolved record: the outcome reference, the design revision, the profile digest and the catalog pin
        resolved = di.stored_inputs(self.store, key, state='confirmed')
        candidate = json.loads(CANDIDATE.read_bytes())
        self.assertEqual((resolved.outcome_ref, resolved.design_revision, resolved.profile_digest,
                          resolved.catalog_pin),
                         (f'{OUTCOME}@{self.design}', f'openspec:changes/{CHANGE}@{self.design}',
                          candidate['profiles'][0]['sha256'], RUN.CATALOG_PIN))
        self.assertEqual(di.attempt_authority(resolved), 'fixture', 'bound to the fixture authority')
        # the attempt receipt, the resolved record's transitions and the result receipt, each labelled fixture
        moves = {e.to_state: json.loads(e.detail_json) for e in self.store.events(key) if e.detail_json}
        self.assertEqual((moves['dispatched']['authority'], moves['confirmed']['authority']), ('fixture', 'fixture'))
        receipt = summary['receipt']
        self.assertEqual((receipt['format'], receipt['authority'], receipt['outcomeRef'], receipt['designRevision']),
                         (RP.RECEIPT_FORMAT, 'fixture', resolved.outcome_ref, resolved.design_revision))
        self.assertEqual(RP.receipt(self.store, attempt_id)['authority'], 'fixture')
        report = json.loads((self.tmp / 'report' / 'report.json').read_text(encoding='utf-8'))
        self.assertEqual(report['authority'], 'fixture')
        pull = self.gitea.pulls[receipt['pullRequest']['number']]
        self.assertIn('| Authority | `fixture` |', pull['body'])
        # every record the fixture attempt causes carries the authority fixture (E-01.7 criterion 11's other half)
        records = [r for r in self.store.attempts() if r.operation_key == key
                   or r.operation_key.startswith(f'dispatch/attempt/{attempt_id}/')]
        self.assertGreaterEqual(len(records), 7, [r.operation_key for r in records])
        for record in records:
            with self.subTest(record=record.operation_key):
                if record.operation_key == key:      # the reservation: its label is its binding (R11)
                    continue
                self.assertIn('"authority":"fixture"', di._canonical(json.loads(record.intent_json)))
        # the review's item 4: the labelled fixture intake receipt is never resumed as live
        base = AR.read_base(self.project, repository=REPOSITORY, design_commit=self.design)
        with self.assertRaises(di.DispatchRefused) as caught:
            AR.recorded_result(self.store, key, base=base)                    # no reader: only a live record
        self.assertEqual(caught.exception.code, 'RESULT_STAGED_UNVERIFIED')
        self.assertEqual(AR.recorded_result(self.store, key, base=base, read_artifact=di.read_profile_artifact)
                         .authority, 'fixture')
        # the result commit: author and committer the commissioning user's configured identity
        commit = self.remote.repo[receipt['commit'].encode('ascii')]
        name_email = IDENTITY.encode('utf-8')
        self.assertEqual((commit.author, commit.committer), (name_email, name_email))
        # no credential entry of the host's is read; the native token's entry is untouched
        self.assertEqual(sorted(set(self.credentials.reads)), sorted([NT.ENTRY, RP.roles.target('builder')]))
        credentials = REPO / 'integrations' / 'credentials'
        self.assertEqual([m for m in loaded if (getattr(sys.modules[m], '__file__', None) or '')
                          and Path(sys.modules[m].__file__).is_relative_to(credentials)], [])
        self.assertEqual(self.constructed, [], 'the host credential provider is never constructed')
        self.assertEqual([e for e in Audit.events if e[0] == 'ctypes.dlopen' and 'advapi32' in e[1].lower()], [])
        self.assertEqual([e for e in Audit.events if e[0] == 'import'
                          and ('keyring' in e[1] or 'credential_provider' in e[1])], [])

    def test_a_live_provider_is_refused_and_the_attempt_is_never_recorded_as_live(self):
        live_provider = NS_provider()
        with self.assertRaises(RUN.RunRefused) as caught:
            self.run_composition(credentials=live_provider)
        self.assertEqual(caught.exception.code, 'CREDENTIAL_AUTHORITY_MISMATCH')
        self.assertEqual(live_provider.reads, [], 'no entry read')
        [attempt] = [r for r in self.store.attempts() if r.operation_key.startswith('attempt/')]
        self.assertEqual(attempt.state, 'failed')
        failed = json.loads(self.store.events(attempt.operation_key)[-1].detail_json)
        self.assertEqual(failed['authority'], 'fixture')


def NS_provider():
    native_support = S.load('native_support', S.DISPATCH_TESTS / 'native_support.py')
    return native_support.ObservedProvider({NT.ENTRY: (NT.ENTRY_USER, backend.native_token())})


class PinnedCommit(unittest.TestCase):
    """The candidate's pin names the harness commit that added the fixture pin's assignment: in a clone holding it,
    the assignment there passes the resolver's own check and assigns the fixture profile's admitted template."""
    category = 'integration'

    def test_the_assignment_at_the_pinned_commit_passes_the_resolvers_check(self):
        candidate = json.loads(CANDIDATE.read_bytes())
        pin = candidate['catalog_pins'][0]
        self.assertEqual(pin['manifest_sha256'], hashlib.sha256((REPO / di.assignment_path(pin['id'])).read_bytes())
                         .hexdigest())
        self.assertEqual(candidate['profiles'][0]['sha256'],
                         hashlib.sha256((REPO / 'profiles' / RUN.PROFILE / 'profile.json').read_bytes()).hexdigest())
        if not (REPO / '.git').exists():
            self.skipTest('this copy has no git history: the pinned commit cannot be read here')
        if di.planning.Git(REPO).commit(pin['commit']) != pin['commit']:
            self.skipTest(f'the pinned commit {pin["commit"]} is not in this clone')
        assignment = di.read_assignment(pin, di.harness_catalog_sources)
        declared = json.loads((REPO / 'profiles' / RUN.PROFILE / 'profile.json').read_bytes())
        self.assertEqual(assignment['create_template'],
                         di.admission_policy(declared, RUN.PROFILE, RUN.STAGE)['create_template'])


if __name__ == '__main__':
    unittest.main()
