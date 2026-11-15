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
* an assignment that names a Skill is refused, and one that is not agent-assignment/v1 for its pin, or whose
  provider is not a registry extract (``RefusesSkillsAndInvalidAssignments``);
* an assignment whose create template is not the one the resolved profile admits for the stage is refused,
  CATALOG_TEMPLATE_NOT_ADMITTED, and accepted when it is (``TheAdmittedTemplate``; review ruling R-dev2);
* every catalog refusal comes before any Backlog.md read and reserves nothing.

The checked-in D1 assignment (``catalog/assignments/d1-implement.json``): its entries are the provider adapter's
registry entry, the create template the checked-in profile admits for the D1 stage, and zero Skills
(``TheCheckedInAssignment``); pinned, it resolves and dispatches the native D1 create on the checked-in profile with
no Skill anywhere in the create and nothing in the workspace, and is refused for the review stage, whose template
is another (``NoSkillIsMaterialized``). The live source reads the committed tree entry and blob of a real git
repository, never its work tree, and refuses an entry that is not a regular file or an object that is missing or
corrupt (``TheGitCatalogSource``: throwaway repositories written with Dulwich's object API, no git process).
"""
from pathlib import Path
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
QUALIFICATION_FIXTURE = 'integrations/dispatch/qualification/acp-claude-code-create.json'
FAKE_REGISTRY = 'integrations/dispatch/qualification/not-a-registry.json'
FAKE_REGISTRY_BYTES = json.dumps({'format': 'not-a-registry', 'acp_server': 'claude-code', 'skills': ['x']}).encode()


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
        sha256 unless given), written as it is (not ``assign``ed)."""
        self.catalog.put(cs.CATALOG, commit, {BUILDER_PATH: raw, **(files or {})})
        data = self.manifest_data()
        pin = data['catalog_pins'][0]
        pin.update(commit=commit, manifest_sha256=digest or hashlib.sha256(raw).hexdigest())
        return self.write_manifest(data, f'pinned-{hashlib.sha256(raw).hexdigest()[:12]}-{commit[:4]}.json',
                                   assign=False)

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
                                              (cs.CATALOG, cs.PIN_COMMIT, cs.REGISTRY_PATH)])

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
        manifest = self.write_manifest(self.manifest_data())
        self.catalog.put(cs.CATALOG, cs.PIN_COMMIT, {BUILDER_PATH: cs.BUILDER_BYTES + b'\n'})
        refusal = self.assertCatalogRefused('CATALOG_MANIFEST_DRIFTED', manifest=manifest)
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
        # Refused before the provider file is read.
        self.assertEqual(self.catalog.reads, [(cs.CATALOG, cs.PIN_COMMIT, BUILDER_PATH)])

    def test_invalid_assignments(self):
        def changed(edit):
            return cs.assignment('builder-pin', change=edit)

        fixture_sha = cs.sha256(cs.checked_in(QUALIFICATION_FIXTURE))
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
            'a provider not at the commit': changed(lambda d: d['provider'].update(
                path='integrations/dispatch/qualification/absent.json')),
            'a provider with another digest': changed(lambda d: d['provider'].update(sha256='0' * 64)),
            'another acp server': changed(lambda d: d['provider'].update(acp_server='codex')),
            # The registry extract's own bytes, at the commit, but outside the registry directory (review N1).
            'a provider outside the registry directory': changed(lambda d: d['provider'].update(
                path='catalog/other/registry.json')),
            'a provider that is no registry extract': changed(lambda d: d['provider'].update(
                path=QUALIFICATION_FIXTURE, sha256=fixture_sha)),
            # Review probe P6: any JSON object naming the acp_server, under the directory, is not a registry extract.
            'a provider of another format naming the server': changed(lambda d: d['provider'].update(
                path=FAKE_REGISTRY, sha256=cs.sha256(FAKE_REGISTRY_BYTES))),
        }
        files = {QUALIFICATION_FIXTURE: cs.checked_in(QUALIFICATION_FIXTURE), FAKE_REGISTRY: FAKE_REGISTRY_BYTES,
                 'catalog/other/registry.json': cs.checked_in(cs.REGISTRY_PATH)}
        for name, raw in cases.items():
            with self.subTest(name):
                self.assertCatalogRefused('CATALOG_MANIFEST_INVALID', manifest=self.pin_builder(raw, files=files))

    def test_an_entry_that_is_not_a_regular_file(self):
        """A symbolic link, an executable or a submodule entry, for the assignment or the provider (review N2)."""
        manifest = self.write_manifest(self.manifest_data())
        for path in (BUILDER_PATH, cs.REGISTRY_PATH):
            with self.subTest(path):
                self.catalog.not_regular = {(cs.CATALOG, cs.PIN_COMMIT, path)}
                refusal = self.assertCatalogRefused('CATALOG_MANIFEST_INVALID', manifest=manifest)
                self.assertIn('not a regular file', refusal.detail)


class TheAdmittedTemplate(Catalogued):
    """Review ruling R-dev2: the assignment's create_template (path and sha256) must be the template the resolved
    profile admits for the request's stage (its stage create template, or its F-04.2 fixture for a stage without
    one)."""

    def test_the_admitted_template_is_accepted(self):
        record = self.resolve(manifest=self.pin_builder(cs.assignment('builder-pin', template=cs.FIXTURE_TEMPLATE)))
        self.assertEqual(record.policy_inputs['admission']['create_template'], cs.FIXTURE_TEMPLATE)

    def test_another_template_is_refused(self):
        other = dict(cs.FIXTURE_TEMPLATE, path='profiles/strong-unbound/agent-server/conversation-create.json')
        cases = {
            'another profile\'s D1 template': {'path': 'profiles/strong-windows-qemu-whpx/agent-server/d1-create.json',
                                               'sha256': cs.sha256(cs.checked_in(
                                                   'profiles/strong-windows-qemu-whpx/agent-server/d1-create.json'))},
            'the admitted path, another digest': dict(cs.FIXTURE_TEMPLATE, sha256='0' * 64),
            'the admitted digest, another path': other,
        }
        for name, template in cases.items():
            with self.subTest(name):
                raw = cs.assignment('builder-pin', template=template)
                refusal = self.assertCatalogRefused('CATALOG_TEMPLATE_NOT_ADMITTED', manifest=self.pin_builder(raw))
                self.assertEqual((refusal.context['assigned'], refusal.context['admitted']),
                                 (template, cs.FIXTURE_TEMPLATE))

    def test_one_pin_bound_to_profiles_that_admit_other_templates(self):
        """builder-pin is bound to strong-test-profile and strong-unbound, each admitting its own copy of the fixture
        (another path): the assignment fits the first only."""
        data = self.manifest_data()
        data['bindings'][0]['profiles'].append('strong-unbound')
        manifest = self.write_manifest(data, 'two-profiles.json', assign=False)
        self.assertEqual(self.resolve(manifest=manifest).agent_manifest_digest, cs.BUILDER_SHA)
        self.ordinal_calls.clear()
        self.sources['demo-app'].reads = 0
        request =self.request(profile='strong-unbound')
        request['catalog_pin'] = 'builder-pin'  # not the fixture's own pin of that profile
        self.assertCatalogRefused('CATALOG_TEMPLATE_NOT_ADMITTED', manifest=manifest, request=request)


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
        # The resolver's view of the checked-in profile: the assignment's template is the one it admits for implement.
        declared = json.loads(checked_in.REAL_BYTES)
        self.assertEqual(di.admission_policy(declared, checked_in.REAL, 'implement')['create_template'],
                         assignment['create_template'])
        self.assertNotEqual(di.admission_policy(declared, checked_in.REAL, 'review')['create_template'],
                            assignment['create_template'])

    def test_the_registry_constants_are_the_qualifications(self):
        self.assertEqual(di.REGISTRY_EXTRACT_FORMAT, aq.REGISTRY_FORMAT)
        self.assertTrue(aq.REGISTRY_PATH.startswith(di.REGISTRY_DIR))

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

    def approve_with_d1_pin(self, stages=('implement',)):
        self.catalog.put(di.CATALOG_REPOSITORY, HARNESS_COMMIT, {
            D1_PATH: D1_BYTES, aq.REGISTRY_PATH: cs.checked_in(aq.REGISTRY_PATH)})
        manifest = self.approve_real()
        data = manifest.data
        data['version'] += 1
        data['catalog_pins'].append({'id': D1_PIN, 'repository': di.CATALOG_REPOSITORY, 'commit': HARNESS_COMMIT,
                                     'manifest_sha256': hashlib.sha256(D1_BYTES).hexdigest()})
        for binding in data['bindings']:
            if binding['stage'] in stages:
                binding['catalog_pins'].append(D1_PIN)
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

    def test_the_d1_pin_is_refused_for_the_review_stage(self):
        """Bound to other-app/review too, the D1 assignment is refused there: the profile admits its F-04.2 fixture
        for review, not the D1 template."""
        manifest = self.approve_with_d1_pin(stages=('implement', 'review'))
        with self.assertRaises(di.DispatchRefused) as caught:
            self.resolve_real(manifest, repository='other-app', stage='review', catalog_pin=D1_PIN)
        self.assertEqual(caught.exception.code, 'CATALOG_TEMPLATE_NOT_ADMITTED')
        self.assertEqual(caught.exception.context['admitted'], checked_in.FIXTURE_PIN)
        self.assertEqual(self.resolve_real(manifest, catalog_pin=D1_PIN).catalog_pin, D1_PIN)
        self.assertEqual(self.store.attempts(), [])

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


def write_repository(root: Path, commits):
    """A repository at ROOT written with Dulwich's object API (no git process): one commit per item of COMMITS,
    each ``{path: (mode, content)}`` (content bytes for a blob, a hex id for a gitlink); ``refs/heads/main`` at the
    last. Returns (the commit ids, {(commit index, path): blob id})."""
    D = di.planning.repository_access.dulwich_modules()
    repo = D.repo.Repo.init(str(root), mkdir=True, config=D.config.StackedConfig([]))
    ids, blobs, parent = [], {}, []
    try:
        for index, files in enumerate(commits):
            objects, trees = [], {}
            for path, (mode, content) in files.items():
                *dirs, name = path.split('/')
                if isinstance(content, bytes):
                    blob = D.objects.Blob.from_string(content)
                    objects.append(blob)
                    oid = blob.id
                    blobs[(index, path)] = oid.decode('ascii')
                else:
                    oid = content.encode('ascii')
                trees.setdefault(tuple(dirs), {})[name.encode()] = (mode, oid)
                for depth in range(len(dirs)):
                    trees.setdefault(tuple(dirs[:depth]), {})
            built = {}
            for key in sorted(trees, key=len, reverse=True):
                tree = D.objects.Tree()
                for name, (mode, oid) in trees[key].items():
                    tree.add(name, mode, oid)
                for child, child_tree in built.items():
                    if len(child) == len(key) + 1 and child[:len(key)] == key:
                        tree.add(child[-1].encode(), 0o040000, child_tree.id)
                built[key] = tree
                objects.append(tree)
            commit = D.objects.Commit()
            commit.tree, commit.parents = built[()].id, parent
            commit.author = commit.committer = b'catalog test <catalog@localhost.invalid>'
            commit.author_time = commit.commit_time = 1_763_164_800 + index
            commit.author_timezone = commit.commit_timezone = 0
            commit.message = b'catalog\n'
            for obj in objects + [commit]:
                repo.object_store.add_object(obj)
            parent = [commit.id]
            ids.append(commit.id.decode('ascii'))
        repo.refs[b'refs/heads/main'] = parent[0]
        repo.refs.set_symbolic_ref(b'HEAD', b'refs/heads/main')
    finally:
        repo.close()
    return ids, blobs


class TheGitCatalogSource(unittest.TestCase):
    """GitCatalogSource reads the committed tree entry and blob at the pinned commit of a real repository, never its
    work tree."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='aieh-catalog-'))
        registry = (aq.REGISTRY_PATH, (0o100644, cs.checked_in(aq.REGISTRY_PATH)))
        cls.commits, cls.blobs = write_repository(cls.tmp / 'catalog', [
            {D1_PATH: (0o100644, D1_BYTES), registry[0]: registry[1]},
            {D1_PATH: (0o100644, D1_BYTES + b' ')},
            {D1_PATH: (0o120000, D1_BYTES)},        # a symbolic link whose target text is the assignment
            {D1_PATH: (0o100755, D1_BYTES)},        # an executable
            {D1_PATH: (0o160000, 'a' * 40)},        # a submodule
        ])
        # The work tree holds yet other bytes: the source never reads it.
        (cls.tmp / 'catalog' / 'catalog' / 'assignments').mkdir(parents=True)
        (cls.tmp / 'catalog' / D1_PATH).write_bytes(b'{"work tree": true}\n')
        cls.source = di.GitCatalogSource(cls.tmp / 'catalog')

    @classmethod
    def tearDownClass(cls):
        base.rmtree(cls.tmp)

    def pin(self, commit, data=D1_BYTES):
        return {'id': D1_PIN, 'repository': di.CATALOG_REPOSITORY, 'commit': commit,
                'manifest_sha256': hashlib.sha256(data).hexdigest()}

    def refused(self, pin, source=None):
        with self.assertRaises(di.DispatchRefused) as caught:
            di.read_assignment(pin, {di.CATALOG_REPOSITORY: source or self.source}.get)
        return caught.exception.code

    def test_it_reads_the_blob_at_each_commit(self):
        first, second = self.commits[:2]
        self.assertEqual(self.source.read(first, D1_PATH), D1_BYTES)
        self.assertEqual(self.source.read(second, D1_PATH), D1_BYTES + b' ')
        self.assertEqual(di.read_assignment(self.pin(first), {di.CATALOG_REPOSITORY: self.source}.get),
                         json.loads(D1_BYTES))

    def test_absent_commit_or_path_is_none(self):
        self.assertIsNone(self.source.read('0' * 40, D1_PATH))
        self.assertIsNone(self.source.read(self.commits[0], 'catalog/assignments/other.json'))
        self.assertIsNone(self.source.read(self.commits[0], 'catalog/other/d1-implement.json'))

    def test_an_unreadable_repository_is_unavailable(self):
        with self.assertRaises(di.CatalogUnavailable):
            di.GitCatalogSource(self.tmp / 'missing').read(self.commits[0], D1_PATH)

    def test_the_resolver_refuses_a_changed_commit(self):
        """Pinned with the first commit's digest at the second commit (one byte more), it is DRIFTED; at the second
        commit with its own digest, its provider is absent there: INVALID."""
        second = self.commits[1]
        self.assertEqual(self.refused(self.pin(second)), 'CATALOG_MANIFEST_DRIFTED')
        self.assertEqual(self.refused(self.pin(second, D1_BYTES + b' ')), 'CATALOG_MANIFEST_INVALID')

    def test_an_entry_that_is_not_a_regular_file(self):
        """Review N2: a symbolic link, an executable or a submodule entry is CATALOG_MANIFEST_INVALID, whatever its
        bytes."""
        for label, commit in zip(('symbolic link', 'executable', 'submodule'), self.commits[2:]):
            with self.subTest(label):
                with self.assertRaises(di.CatalogEntryNotRegular):
                    self.source.read(commit, D1_PATH)
                self.assertEqual(self.refused(self.pin(commit)), 'CATALOG_MANIFEST_INVALID')

    def test_a_missing_or_corrupt_object_is_unavailable(self):
        """Review probe 4: the blob missing or corrupt, or the tree corrupt, is CATALOG_SOURCE_UNAVAILABLE."""
        for label in ('blob missing', 'blob corrupt', 'tree corrupt'):
            with self.subTest(label):
                root = self.tmp / label.replace(' ', '-')
                (commit,), blobs = write_repository(root, [{D1_PATH: (0o100644, D1_BYTES)}])
                if label == 'tree corrupt':
                    D = di.planning.repository_access.dulwich_modules()
                    tree = D.objects.Tree()
                    tree.add(b'd1-implement.json', 0o100644, blobs[(0, D1_PATH)].encode('ascii'))
                    target = tree.id.decode('ascii')
                else:
                    target = blobs[(0, D1_PATH)]
                obj = root / '.git' / 'objects' / target[:2] / target[2:]
                obj.chmod(0o644)
                if label == 'blob missing':
                    obj.unlink()
                else:
                    obj.write_bytes(b'\x78\x9cgarbage-not-zlib')
                self.assertEqual(self.refused(self.pin(commit), di.GitCatalogSource(root)),
                                 'CATALOG_SOURCE_UNAVAILABLE')


if __name__ == '__main__':
    unittest.main()
