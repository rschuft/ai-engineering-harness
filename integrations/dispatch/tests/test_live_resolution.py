"""Tests for the live resolution command (plan leaf E-05.3): ``dispatch_inputs.resolve_live`` and ``resolve``.

Run from the repository root, under the tools interpreter (Dulwich is required):

    <tools python> -I -B -m unittest discover -s integrations/dispatch/tests -p test_live_resolution.py -v

A throwaway managed data root (``aieh_paths.resolve`` with ``AIEH_DATA_ROOT`` and no configuration file) holds the
integration store at its managed location and the live manifest; the manifest is promoted there by the REAL
recorder (``integrations/owner/input_recorder.py``, the Owner path with a synthetic statement, through the
dispatch-input commands' own fixture ``integrations/owner/tests/input_fixture.py``), and loaded by the REAL
verifier. The request's Work is an in-memory readiness entry whose source pointer is made on the fixture's project
repository; the profile is the checked-in ``strong-windows-qemu-whpx``; the catalog is ``catalog_support``'s.
Nothing is reserved, and no live store, Backlog.md, Gitea or credential is used.
"""
from pathlib import Path
import hashlib
import importlib.util
import json
import sys
import unittest
from unittest import mock

CATEGORY = 'integration'

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / 'integrations' / 'owner' / 'tests'))
import input_fixture as fi  # noqa: E402

DI, IS = fi.DI, fi.IS


def _load(name, path):
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


cs = _load('dispatch_catalog_support', HERE / 'catalog_support.py')
REAL = 'strong-windows-qemu-whpx'
REAL_SHA = hashlib.sha256((REPO / 'profiles' / REAL / 'profile.json').read_bytes()).hexdigest()
OUTCOME_REF = 'outcome:3f6a2c1d-9b4e-4f7a-8c2d-5e1b0a9f7d63'


def setUpModule():
    fi.start()


def tearDownModule():
    fi.stop()


class Entry:
    """The request's Work: one ready readiness entry with one resolved pointer and one outcome reference."""

    def __init__(self, pointer):
        self.pointer, self.reads = pointer, 0

    def read(self, work_id):
        self.reads += 1
        return {'reasons': [], 'eligible': True, 'pointers': [{'pointer': self.pointer, 'resolved': True}],
                'references': [OUTCOME_REF]}


class LiveResolution(fi.Fixture):
    def setUp(self):
        super().setUp()
        self.res = DI.paths.resolve({'AIEH_DATA_ROOT': str(self.dir / 'root')}, config={})
        self.store_path = DI.live_store_path(self.res)
        self.store_path.parent.mkdir(parents=True)
        DI.manifest_path(self.res).parent.mkdir(parents=True)
        self.live_store = IS.open_store(self.store_path)
        self.addCleanup(self.live_store.close)
        self.ctx = self.context(state_root=Path(str(self.res.paths['state'])), store=self.live_store,
                                manifest_path=DI.manifest_path(self.res))
        self.catalog = cs.standard()
        git = DI.planning.Git(self.repos.project)
        self.work = Entry(DI.planning.make_pointer(git, fi.CHANGE, 'design.md', self.repos.first).text)

    def promote_candidate(self):
        pin = {'id': 'builder-pin', 'repository': cs.CATALOG, 'commit': cs.PIN_COMMIT,
               'manifest_sha256': cs.BUILDER_SHA}
        self.accept()
        self.promote(self.candidate(profiles=[{'id': REAL, 'sha256': REAL_SHA}], catalog_pins=[pin],
                                    bindings=[{'repository': fi.REPOSITORY, 'stage': 'implement',
                                               'profiles': [REAL], 'catalog_pins': ['builder-pin']}]))

    def request(self, **changes):
        return {'format': DI.REQUEST_FORMAT, 'work_id': 'TASK-1', 'repository': fi.REPOSITORY, 'stage': 'implement',
                'profile': REAL, 'catalog_pin': 'builder-pin', **changes}

    def resolve(self, request=None):
        return DI.resolve_live(self.request() if request is None else request, res=self.res, work_source=self.work,
                               catalog_sources=self.catalog.sources)

    def attempts(self):
        return [r.operation_key for r in self.live_store.attempts() if r.operation_key.startswith('attempt/')]

    def test_a_promoted_manifest_resolves_the_task_and_reserves_nothing(self):
        self.promote_candidate()
        resolved, manifest = self.resolve()
        self.assertEqual((resolved.work_id, resolved.repository, resolved.stage, resolved.ordinal),
                         ('TASK-1', fi.REPOSITORY, 'implement', 1))
        self.assertEqual(resolved.design_revision, f'openspec:changes/{fi.CHANGE}@{self.repos.first}')
        self.assertEqual((resolved.profile_digest, resolved.catalog_pin, resolved.agent_manifest_digest),
                         (REAL_SHA, 'builder-pin', cs.BUILDER_SHA))
        self.assertEqual(resolved.outcome_ref, OUTCOME_REF)
        self.assertEqual((resolved.manifest_version, manifest.version), (1, 1))
        self.assertEqual(manifest.approving_record('catalog_pins', 'builder-pin')['kind'], 'promote-manifest')
        self.assertEqual(self.attempts(), [])
        self.assertEqual(self.work.reads, 1)

    def test_a_refusal_after_the_load_is_the_resolvers(self):
        self.promote_candidate()
        self.catalog.put(cs.CATALOG, cs.PIN_COMMIT, {'catalog/assignments/builder-pin.json': cs.BUILDER_BYTES + b' '})
        with self.assertRaises(DI.DispatchRefused) as caught:
            self.resolve()
        self.assertEqual(caught.exception.code, 'CATALOG_MANIFEST_DRIFTED')
        self.assertEqual((self.attempts(), self.work.reads), ([], 0))

    def test_an_unpromoted_or_changed_manifest_is_refused(self):
        with self.assertRaises(DI.DispatchRefused) as caught:
            self.resolve()
        self.assertEqual(caught.exception.code, 'MANIFEST_MISSING')
        self.promote_candidate()
        live = DI.manifest_path(self.res)
        live.write_bytes(live.read_bytes() + b'\n')
        with self.assertRaises(DI.DispatchRefused) as caught:
            self.resolve()
        self.assertEqual(caught.exception.code, 'MANIFEST_DIGEST_MISMATCH')

    def test_no_store_at_its_managed_location(self):
        self.live_store.close()
        self.store_path.unlink()
        with self.assertRaises(DI.LiveUnavailable):
            self.resolve()
        self.assertFalse(self.store_path.exists(), 'the store is never created here')

    def test_the_command_line(self):
        request = self.dir / 'request.json'
        request.write_text(json.dumps(self.request()), encoding='utf-8')
        argv = ['resolve', '--request', str(request), '--project', str(self.repos.project), '--backlog', 'backlog']
        with mock.patch.object(DI.paths, 'resolve', lambda environ=None: self.res), \
                mock.patch.object(DI.planning, 'tool_argv', lambda spec: [spec]), \
                mock.patch.object(DI, 'PlanningWorkSource', lambda backlog, git: self.work), \
                mock.patch('sys.stdout') as out, mock.patch('sys.stderr'):
            self.assertEqual(DI.main(argv), 1)  # nothing promoted: MANIFEST_MISSING, as a refusal record
            printed = ''.join(call.args[0] for call in out.write.call_args_list)
            self.assertEqual(json.loads(printed)['code'], 'MANIFEST_MISSING')
            self.assertEqual(DI.main(['resolve', '--request', str(self.dir / 'absent.json'), '--project', '.',
                                      '--backlog', 'backlog']), 2)
            self.live_store.close()
            self.store_path.unlink()
            self.assertEqual(DI.main(argv), 2)


if __name__ == '__main__':
    unittest.main()
