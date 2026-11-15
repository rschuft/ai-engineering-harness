"""Tests for the digest-bound agent assignment of a catalog pin (plan leaf E-05.3), offline.

Run from the repository root:

    python -I -B -m unittest discover -s integrations/dispatch/tests -p test_agent_assignment.py -v

The proof's resolver clauses, through ``dispatch_inputs.resolve`` on the E-01.2.1 fixture (a throwaway design
repository, profiles, manifest and store) with an in-memory catalog (``catalog_support``):

* the pinned agent assignment is accepted, read at the pinned commit of the pin's catalog repository
  (``AcceptsThePinnedAssignment``);
* an unpinned assignment is refused: no pin named, a pin the manifest does not approve or bind, no approved pin at
  all, and an assignment that is not at the pinned commit (``RefusesAnUnpinnedAssignment``);
* an assignment with a different digest is refused, CATALOG_MANIFEST_DRIFTED (``RefusesADifferentDigest``);
* an assignment that names a Skill is refused, and one that is not agent-assignment/v1 for its pin
  (``RefusesSkillsAndInvalidAssignments``);
* every catalog refusal comes before any Backlog.md read and reserves nothing.

The checked-in D1 assignment (``catalog/assignments/d1-implement.json``): its entries are the provider adapter's
registry entry, the create template the checked-in profile admits for the D1 stage, and zero Skills
(``TheCheckedInAssignment``); pinned, it resolves and dispatches the native D1 create on the checked-in profile with
no Skill anywhere in the create and nothing in the workspace (``NoSkillIsMaterialized``). The live source reads the
committed blob of a real git repository, never its work tree (``TheGitCatalogSource``, a throwaway repository
written with Dulwich's object API: no git process).
"""
from pathlib import Path
import copy
import hashlib
import importlib.util
import json
import sys
import tempfile
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


checked_in = _load('test_d1_checked_in_template', HERE / 'test_d1_checked_in_template.py')
native_tests = checked_in.native_tests
base, di, cc, NT = checked_in.base, checked_in.di, checked_in.cc, checked_in.NT
cs = base.cs
aq = _load('aieh_acp_qualification', base.DISPATCH / 'acp_qualification.py')

D1_PIN = 'd1-implement'
D1_PATH = f'catalog/assignments/{D1_PIN}.json'
D1_BYTES = (base.REPO / D1_PATH).read_bytes()
HARNESS_COMMIT = 'e' * 40
BUILDER_PATH = 'catalog/assignments/builder-pin.json'


def walk_keys(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from walk_keys(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk_keys(value)


class Catalogued(base.Fixture):
    """The resolver's fixture with helpers to pin other assignment bytes for builder-pin."""

    def pin_builder(self, raw, *, digest=None, commit=cs.PIN_COMMIT, files=None):
        """RAW as builder-pin's assignment at COMMIT (with FILES), and a manifest pinning it by DIGEST (its own
        sha256 unless given)."""
        self.catalog.put(cs.CATALOG, commit, {BUILDER_PATH: raw, **(files or {})})
        data = self.manifest_data()
        pin = data['catalog_pins'][0]
        pin.update(commit=commit, manifest_sha256=digest or hashlib.sha256(raw).hexdigest())
        return self.write_manifest(data, f'pinned-{hashlib.sha256(raw).hexdigest()[:12]}-{commit[:4]}.json')

    def assertCatalogRefused(self, code, manifest=None, request=None):
        refusal = self.assertRefused(code, request=request, manifest=manifest)
        self.assertEqual(self.sources['demo-app'].reads, 0, 'a catalog refusal comes before any Backlog.md read')
        return refusal


class AcceptsThePinnedAssignment(Catalogued):
    def test_the_pinned_assignment_is_accepted_at_its_pinned_commit(self):
        record = self.resolve()
        self.assertEqual((record.catalog_pin, record.agent_manifest_digest), ('builder-pin', cs.BUILDER_SHA))
        self.assertEqual(record.policy_inputs['catalog_pin'],
                         {'id': 'builder-pin', 'repository': cs.CATALOG, 'commit': cs.PIN_COMMIT,
                          'manifest_sha256': cs.BUILDER_SHA})
        self.assertEqual(self.catalog.reads, [(cs.CATALOG, cs.PIN_COMMIT, BUILDER_PATH),
                                              (cs.CATALOG, cs.PIN_COMMIT, cs.REGISTRY_PATH),
                                              (cs.CATALOG, cs.PIN_COMMIT, cs.D1_TEMPLATE_PATH)])

    def test_read_assignment_returns_the_checked_assignment(self):
        pin = self.manifest_data()['catalog_pins'][0]
        self.assertEqual(di.read_assignment(pin, self.catalog.sources), json.loads(cs.BUILDER_BYTES))

    def test_another_commit_of_the_catalog_does_not_change_what_is_read(self):
        """A later commit (or a work tree) holding other bytes for the pin's path is not the pinned assignment."""
        self.catalog.put(cs.CATALOG, 'd' * 40, {BUILDER_PATH: cs.assignment('builder-pin', skills=['other'])})
        self.assertEqual(self.resolve().agent_manifest_digest, cs.BUILDER_SHA)


class RefusesAnUnpinnedAssignment(Catalogued):
    def test_no_pin_named(self):
        request = self.request()
        del request['catalog_pin']
        self.assertCatalogRefused('CATALOG_PIN_REQUIRED', request=request)

    def test_an_assignment_no_pin_approves_is_never_read(self):
        """An assignment present in the catalog whose pin the manifest does not approve is refused before any
        catalog read."""
        self.catalog.put(cs.CATALOG, cs.PIN_COMMIT, {'catalog/assignments/rogue-pin.json': cs.assignment('rogue-pin')})
        self.assertCatalogRefused('CATALOG_PIN_UNKNOWN', request=self.request(catalog_pin='rogue-pin'))
        self.assertCatalogRefused('CATALOG_PIN_NOT_BOUND', request=self.request(catalog_pin='reviewer-pin'))
        self.assertEqual(self.catalog.reads, [])

    def test_no_approved_pin_at_all(self):
        data = self.manifest_data()
        data['catalog_pins'] = []
        for binding in data['bindings']:
            binding['catalog_pins'] = []
        self.assertCatalogRefused('NO_APPROVED_CATALOG', manifest=self.write_manifest(data, 'no-catalog.json'))
        self.assertEqual(self.catalog.reads, [])

    def test_an_assignment_not_at_the_pinned_commit(self):
        # The assignment exists only at another commit; the pin names a commit without it.
        manifest = self.pin_builder(cs.BUILDER_BYTES, commit='d' * 40)
        self.catalog.repositories[cs.CATALOG]['d' * 40].pop(BUILDER_PATH)
        refusal = self.assertCatalogRefused('CATALOG_MANIFEST_MISSING', manifest=manifest)
        self.assertEqual(refusal.context['path'], BUILDER_PATH)

    def test_a_pinned_commit_the_catalog_does_not_have(self):
        data = self.manifest_data()
        data['catalog_pins'][0]['commit'] = 'f' * 40
        self.assertCatalogRefused('CATALOG_MANIFEST_MISSING', manifest=self.write_manifest(data, 'absent.json'))

    def test_no_catalog_source(self):
        data = self.manifest_data()
        data['catalog_pins'][0]['repository'] = 'unknown-catalog'
        self.assertCatalogRefused('CATALOG_SOURCE_UNAVAILABLE', manifest=self.write_manifest(data, 'source.json'))

    def test_a_source_that_fails_or_returns_no_bytes(self):
        manifest = self.write_manifest(self.manifest_data())
        self.catalog.fail = di.CatalogUnavailable('unreadable')
        self.assertCatalogRefused('CATALOG_SOURCE_UNAVAILABLE', manifest=manifest)
        self.catalog.fail = None

        class TextSource:
            def read(self, commit, path):
                return 'not bytes'
        with self.assertRaises(di.DispatchRefused) as caught:
            di.read_assignment(self.manifest_data()['catalog_pins'][0], lambda name: TextSource())
        self.assertEqual(caught.exception.code, 'CATALOG_SOURCE_UNAVAILABLE')


class RefusesADifferentDigest(Catalogued):
    def test_the_assignment_at_the_pinned_commit_has_another_digest(self):
        """The catalog's bytes changed under the pin: one byte more is another digest."""
        self.catalog.put(cs.CATALOG, cs.PIN_COMMIT, {BUILDER_PATH: cs.BUILDER_BYTES + b'\n'})
        refusal = self.assertCatalogRefused('CATALOG_MANIFEST_DRIFTED')
        self.assertEqual((refusal.context['approved'], refusal.context['actual']),
                         (cs.BUILDER_SHA, hashlib.sha256(cs.BUILDER_BYTES + b'\n').hexdigest()))

    def test_a_pin_with_a_different_digest(self):
        for digest in (cs.REVIEWER_SHA, '0' * 64):
            with self.subTest(digest=digest):
                data = self.manifest_data()
                data['catalog_pins'][0]['manifest_sha256'] = digest
                self.assertCatalogRefused('CATALOG_MANIFEST_DRIFTED',
                                          manifest=self.write_manifest(data, f'digest-{digest[:6]}.json'))

    def test_the_digest_is_checked_before_the_content(self):
        """A drifted assignment is DRIFTED whatever it says (a Skill included): nothing of it is believed."""
        raw = cs.assignment('builder-pin', skills=['intent-normalization'])
        self.assertCatalogRefused('CATALOG_MANIFEST_DRIFTED', manifest=self.pin_builder(raw, digest=cs.BUILDER_SHA))


class RefusesSkillsAndInvalidAssignments(Catalogued):
    def test_an_assignment_that_names_a_skill(self):
        raw = cs.assignment('builder-pin', skills=['intent-normalization'])
        refusal = self.assertCatalogRefused('CATALOG_SKILL_NOT_QUALIFIED', manifest=self.pin_builder(raw))
        self.assertEqual(refusal.context['catalog_pin'], 'builder-pin')
        # Refused before any file the assignment names is read.
        self.assertEqual(self.catalog.reads, [(cs.CATALOG, cs.PIN_COMMIT, BUILDER_PATH)])

    def test_invalid_assignments(self):
        def changed(edit):
            return cs.assignment('builder-pin', change=edit)

        cases = {
            'not JSON': b'synthetic builder agent/Skill manifest',
            'not UTF-8': b'\xff\xfe{}',
            'a duplicate key': cs.BUILDER_BYTES.replace(b'"skills": []', b'"skills": [], "skills": []'),
            'a JSON constant': cs.BUILDER_BYTES.replace(b'"skills": []', b'"skills": NaN'),
            'not an object': b'[]\n',
            'another format': changed(lambda d: d.update(format='ai-engineering-harness/catalog/agent-assignment/v2')),
            'an extra key': changed(lambda d: d.update(model='claude-sonnet-5')),
            'a missing key': changed(lambda d: d.pop('create_template')),
            'another id': changed(lambda d: d.update(id='reviewer-pin')),
            'skills not a list': changed(lambda d: d.update(skills={})),
            'provider without acp_server': changed(lambda d: d['provider'].pop('acp_server')),
            'provider acp_server not an id': changed(lambda d: d['provider'].update(acp_server='Claude Code')),
            'template with an extra key': changed(lambda d: d['create_template'].update(stage='implement')),
            'a path that climbs': changed(lambda d: d['create_template'].update(path='../d1-create.json')),
            'an absolute path': changed(lambda d: d['create_template'].update(path='/d1-create.json')),
            'a device name': changed(lambda d: d['create_template'].update(path='profiles/CON.json')),
            'a sha256 not lower-case hex': changed(lambda d: d['provider'].update(sha256='A' * 64)),
            'a named file not at the commit': changed(lambda d: d['create_template'].update(path='profiles/x.json')),
            'a named file with another digest': changed(lambda d: d['create_template'].update(sha256='0' * 64)),
            'another acp server': changed(lambda d: d['provider'].update(acp_server='codex')),
            'a provider that is no registry entry': changed(lambda d: d['provider'].update(
                path=cs.D1_TEMPLATE_PATH, sha256=cs.sha256(cs.checked_in(cs.D1_TEMPLATE_PATH)))),
        }
        for name, raw in cases.items():
            with self.subTest(name):
                self.assertCatalogRefused('CATALOG_MANIFEST_INVALID', manifest=self.pin_builder(raw))


class TheCheckedInAssignment(unittest.TestCase):
    """catalog/assignments/d1-implement.json: the provider adapter's registry entry, the create template the
    checked-in profile admits for the D1 stage, zero Skills; each named file at its checked-in digest."""

    def test_its_entries(self):
        assignment = json.loads(D1_BYTES)
        pin = checked_in.PIN
        self.assertEqual(assignment, {
            'format': di.ASSIGNMENT_FORMAT, 'id': D1_PIN,
            'provider': {'path': aq.REGISTRY_PATH, 'sha256': aq.REGISTRY_SHA256, 'acp_server': aq.ACP_SERVER},
            'create_template': {'path': pin['path'], 'sha256': pin['sha256']},
            'skills': []})
        self.assertEqual((pin['stage'], pin[di.EXECUTION_PROFILE_KEY]), ('implement', di.NATIVE))
        self.assertEqual(di.assignment_path(D1_PIN), D1_PATH)

    def test_the_resolver_accepts_its_checked_in_bytes(self):
        """read_assignment over the checked-in files (as a commit holding this work tree would answer)."""
        class WorkTree:
            def read(self, commit, path):
                target = base.REPO / path
                return target.read_bytes() if target.is_file() else None
        pin = {'id': D1_PIN, 'repository': di.CATALOG_REPOSITORY, 'commit': HARNESS_COMMIT,
               'manifest_sha256': hashlib.sha256(D1_BYTES).hexdigest()}
        sources = {di.CATALOG_REPOSITORY: WorkTree()}
        self.assertEqual(di.read_assignment(pin, sources.get), json.loads(D1_BYTES))
        self.assertIsNone(di.harness_catalog_sources('aieh-catalog'))
        self.assertIsInstance(di.harness_catalog_sources(di.CATALOG_REPOSITORY), di.GitCatalogSource)


class NoSkillIsMaterialized(checked_in.CheckedInFixture):
    """The checked-in assignment, pinned at a commit of the harness catalog, on the checked-in profile."""

    def approve_with_d1_pin(self):
        self.catalog.put(di.CATALOG_REPOSITORY, HARNESS_COMMIT, {
            D1_PATH: D1_BYTES, aq.REGISTRY_PATH: cs.checked_in(aq.REGISTRY_PATH),
            checked_in.PIN['path']: cs.checked_in(checked_in.PIN['path'])})
        manifest = self.approve_real()
        data = manifest.data
        data['version'] += 1
        data['catalog_pins'].append({'id': D1_PIN, 'repository': di.CATALOG_REPOSITORY, 'commit': HARNESS_COMMIT,
                                     'manifest_sha256': hashlib.sha256(D1_BYTES).hexdigest()})
        data['bindings'][0]['catalog_pins'].append(D1_PIN)
        return self.write_manifest(data, self.fresh('d1-pin'))

    def test_the_native_d1_create_under_the_pin_carries_no_skill(self):
        server = cc.FakeAgentServer()
        result = di.dispatch(self.real_request(catalog_pin=D1_PIN), manifest=self.approve_with_d1_pin(),
                             work_sources=self.d1_sources.get, integration_store=self.store,
                             workspaces=self.workspaces, transport=server, actor='e-05.3-test',
                             read_profile=self.read_profile, read_artifact=self.read_artifact,
                             inference=native_tests.NoBroker(), native_credentials=self.provider,
                             catalog_sources=self.catalog.sources)
        [(_, _, body)] = server.creates
        self.assertEqual(body, self.sent_body(result.conversation_id))
        self.assertEqual([key for key in walk_keys(body) if 'skill' in key.lower()], [])
        stored = di.stored_inputs(self.store, result.operation_key, state='confirmed')
        self.assertEqual((stored.catalog_pin, stored.agent_manifest_digest),
                         (D1_PIN, hashlib.sha256(D1_BYTES).hexdigest()))
        workspace = Path(di.workspace_host_path(stored, self.workspaces, result.operation_key))
        self.assertTrue(workspace.is_dir())
        self.assertEqual(list(workspace.iterdir()), [], 'nothing (no Skill) is placed in the workspace')

    def test_a_skill_added_to_the_d1_assignment_is_refused(self):
        raw = json.loads(D1_BYTES)
        raw['skills'] = ['intent-normalization']
        changed = (json.dumps(raw, indent=2) + '\n').encode('utf-8')
        manifest = self.approve_with_d1_pin()
        self.catalog.put(di.CATALOG_REPOSITORY, HARNESS_COMMIT, {D1_PATH: changed})
        with self.assertRaises(di.DispatchRefused) as caught:
            self.resolve_real(manifest, catalog_pin=D1_PIN)
        self.assertEqual(caught.exception.code, 'CATALOG_MANIFEST_DRIFTED')
        data = manifest.data
        data['version'] += 1
        data['catalog_pins'][-1]['manifest_sha256'] = hashlib.sha256(changed).hexdigest()
        with self.assertRaises(di.DispatchRefused) as caught:
            self.resolve_real(self.write_manifest(data, self.fresh('skill')), catalog_pin=D1_PIN)
        self.assertEqual(caught.exception.code, 'CATALOG_SKILL_NOT_QUALIFIED')
        self.assertEqual(self.store.attempts(), [])


class TheGitCatalogSource(unittest.TestCase):
    """GitCatalogSource reads the committed blob at the pinned commit of a real repository, never its work tree."""

    @classmethod
    def setUpClass(cls):
        D = di.planning.repository_access.dulwich_modules()
        cls.tmp = Path(tempfile.mkdtemp(prefix='aieh-catalog-'))
        repo = D.repo.Repo.init(str(cls.tmp), config=D.config.StackedConfig([]))
        cls.commits = []
        parent = []
        for content in (D1_BYTES, D1_BYTES + b' '):
            blob = D.objects.Blob.from_string(content)
            assignments = D.objects.Tree()
            assignments.add(f'{D1_PIN}.json'.encode(), 0o100644, blob.id)
            catalog = D.objects.Tree()
            catalog.add(b'assignments', 0o040000, assignments.id)
            root = D.objects.Tree()
            root.add(b'catalog', 0o040000, catalog.id)
            commit = D.objects.Commit()
            commit.tree, commit.parents = root.id, parent
            commit.author = commit.committer = b'catalog test <catalog@localhost.invalid>'
            commit.author_time = commit.commit_time = 1_763_164_800
            commit.author_timezone = commit.commit_timezone = 0
            commit.message = b'catalog\n'
            for obj in (blob, assignments, catalog, root, commit):
                repo.object_store.add_object(obj)
            parent = [commit.id]
            cls.commits.append(commit.id.decode('ascii'))
        repo.refs[b'refs/heads/main'] = parent[0]
        repo.refs.set_symbolic_ref(b'HEAD', b'refs/heads/main')
        repo.close()
        # The work tree holds yet other bytes: the source never reads it.
        (cls.tmp / 'catalog' / 'assignments').mkdir(parents=True)
        (cls.tmp / D1_PATH).write_bytes(b'{"work tree": true}\n')

    @classmethod
    def tearDownClass(cls):
        base.rmtree(cls.tmp)

    def test_it_reads_the_blob_at_each_commit(self):
        source = di.GitCatalogSource(self.tmp)
        first, second = self.commits
        self.assertEqual(source.read(first, D1_PATH), D1_BYTES)
        self.assertEqual(source.read(second, D1_PATH), D1_BYTES + b' ')

    def test_absent_commit_or_path_is_none(self):
        source = di.GitCatalogSource(self.tmp)
        self.assertIsNone(source.read('0' * 40, D1_PATH))
        self.assertIsNone(source.read(self.commits[0], 'catalog/assignments/other.json'))
        self.assertIsNone(source.read(self.commits[0], 'catalog/assignments'))  # a tree, not a blob

    def test_an_unreadable_repository_is_unavailable(self):
        with self.assertRaises(di.CatalogUnavailable):
            di.GitCatalogSource(self.tmp / 'missing').read(self.commits[0], D1_PATH)

    def test_the_resolver_refuses_a_changed_commit(self):
        """Pinned at the first commit, the assignment is accepted; pinned with the first's digest at the second
        commit (one byte more), it is DRIFTED."""
        sources = {di.CATALOG_REPOSITORY: di.GitCatalogSource(self.tmp)}.get
        first, second = self.commits
        digest = hashlib.sha256(D1_BYTES).hexdigest()
        pin = {'id': D1_PIN, 'repository': di.CATALOG_REPOSITORY, 'commit': first, 'manifest_sha256': digest}
        with self.assertRaises(di.DispatchRefused) as caught:   # the named files are not in this repository
            di.read_assignment(pin, sources)
        self.assertEqual(caught.exception.code, 'CATALOG_MANIFEST_INVALID')
        with self.assertRaises(di.DispatchRefused) as caught:
            di.read_assignment(dict(pin, commit=second), sources)
        self.assertEqual(caught.exception.code, 'CATALOG_MANIFEST_DRIFTED')


if __name__ == '__main__':
    unittest.main()
