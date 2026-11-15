"""The D1 demonstration repository's content and its Work records (demo_repository.py; plan leaf E-05.1), offline.

Covered: the initial content (the template tree and the catalog's schema; no dependency, no Claude Code settings or
MCP configuration; a forbidden name or a symbolic link refused) and its own tests passing under this interpreter;
``seed`` on the initialization commit, idempotent, never overwriting a later commit's file; ``place`` byte for byte,
its placement content equal to planning's (decision 0020 point 1), idempotent, refusing a changed change folder and
a placement whose content is not planning's with nothing visible changed; ``verify-placement`` before and after the
acceptance recorder's commit; the Owner's statement admitted by the recorder at this checkout's committed HEAD (read
only); the planning map with the outcome reference; and the whole Work records sequence rehearsed on a throwaway
bare repository standing in for the host Gitea: seed, place, ``record-from-log`` (E-05.12) from this checkout's
committed log, the task created through the planning adapter at the recorder's commit with the outcome, a fresh
clone in which every pointer and the outcome resolve. Backlog.md is ``fake_backlog.py`` there;
``LiveRehearsal`` runs the same sequence with the pinned Backlog.md and OpenSpec and adds Backlog.md's readiness
(P-02.2), and is skipped unless ``AIEH_BACKLOG`` and ``AIEH_OPENSPEC`` name their entry points. Nothing is written
to this checkout, its log, the managed data root or any Gitea; every repository is a throwaway one, and every
acceptance recorded here is in a throwaway repository.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

CATEGORY = 'integration'

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PLANNING_TESTS = REPO / 'integrations' / 'planning' / 'tests'


def _load(name, path):
    if (module := sys.modules.get(name)) is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = sys.modules[name] = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except BaseException:
            del sys.modules[name]
            raise
    return module


DR = _load('aieh_gitea_demo_repository', HERE.parent / 'demo_repository.py')
A = DR._acceptance_recorder()  # first, so that the planning adapter and the repository module are one instance each
sys.path.insert(0, str(PLANNING_TESTS))
import two_task_fixture as fx  # noqa: E402
import fake_backlog  # noqa: E402

P = DR._planning()
IDENTITY = 'E-05.1 Fixture <fixture@example.invalid>'
RECORDED_BY = 'agent:fixture-transcriber'
FAKE_BACKLOG = [sys.executable, '-I', '-B', str(PLANNING_TESTS / 'fake_backlog.py')]
EXPECTED_TEMPLATE = [
    '.gitattributes', '.gitignore', 'README.md', 'aieh_d1_demo/__init__.py', 'backlog/config.yml',
    'openspec/config.yaml', 'openspec/schemas/intent-driven/schema.yaml',
    'openspec/schemas/intent-driven/templates/design.md', 'openspec/schemas/intent-driven/templates/proposal.md',
    'openspec/schemas/intent-driven/templates/spec.md', 'tests/test_package.py']
INIT_README = b'# aieh-d1-demo\n\nThe host\'s initialization commit (a stand-in).\n'


def refused(test, code, call, *args, **kwargs):
    with test.assertRaises(DR.DemoError) as caught:
        call(*args, **kwargs)
    test.assertEqual(caught.exception.code, code, caught.exception)
    return caught.exception


class Content(unittest.TestCase):
    category = 'unit'

    def test_the_initial_content_is_the_template_and_the_catalog_schema(self):
        files = DR.template_files()
        self.assertEqual(list(files), EXPECTED_TEMPLATE)
        schema = REPO / 'catalog' / 'openspec' / 'schemas' / 'intent-driven'
        for path in (p for p in files if p.startswith(DR.SCHEMA_PATH + '/')):
            self.assertEqual(files[path], (schema / path[len(DR.SCHEMA_PATH) + 1:]).read_bytes(), path)
        self.assertEqual(files['openspec/config.yaml'], b'schema: intent-driven\n')
        self.assertIn(b'project_name: "aieh-d1-demo"\n', files['backlog/config.yml'])
        self.assertEqual(files['.gitattributes'].splitlines()[-1], b'* -text')

    def test_no_dependency_no_settings_and_no_change_or_task(self):
        files = DR.template_files()
        for name in ('requirements.txt', 'pyproject.toml', 'setup.py', 'setup.cfg', 'Pipfile', 'package.json',
                     '.mcp.json', 'CLAUDE.md'):
            self.assertNotIn(name, files)
        self.assertFalse([p for p in files if p.split('/')[0] in ('.claude', '.github', '.gitea')
                          or p.startswith(('openspec/changes/', 'backlog/tasks/'))])
        for path, data in files.items():
            self.assertNotIn(b'\r\n', data, path)
            if path.endswith('.py'):
                imports = [line.split()[1] for line in data.decode('utf-8').splitlines()
                           if line.startswith(('import ', 'from '))]
                self.assertTrue(set(imports) <= {'unittest', 'aieh_d1_demo'}, (path, imports))

    def test_a_forbidden_name_or_a_symbolic_link_is_refused(self):
        with tempfile.TemporaryDirectory(prefix='aieh-demo-') as tmp:
            root = Path(tmp) / 'template'
            for name in ('.claude', '.mcp.json'):
                with self.subTest(name=name):
                    fx.rmtree(root) if root.exists() else None
                    (root / 'a').mkdir(parents=True)
                    target = root / 'a' / name
                    target.mkdir() if name == '.claude' else target.write_bytes(b'{}')
                    with mock.patch.object(DR, 'TEMPLATE', root):
                        refused(self, 'CONTENT_FORBIDDEN', DR.template_files)
            fx.rmtree(root)
            root.mkdir()
            (root / 'x.txt').write_bytes(b'x\n')
            (root / '__pycache__').mkdir()
            (root / '__pycache__' / 'x.pyc').write_bytes(b'\0')
            with mock.patch.object(DR, 'TEMPLATE', root):
                self.assertEqual([p for p in DR.template_files() if not p.startswith('openspec/')], ['x.txt'])
            try:
                os.symlink(root / 'x.txt', root / 'link.txt')
            except OSError:
                return  # no symbolic link privilege here: the walk's refusal stays covered by the names above
            with mock.patch.object(DR, 'TEMPLATE', root):
                refused(self, 'CONTENT_FORBIDDEN', DR.template_files)

    def test_the_design_files_are_planning_s_placement(self):
        files = DR.design_files()
        self.assertEqual([p[len(DR.CHANGE_PATH) + 1:] for p in files],
                         ['.openspec.yaml', 'design.md', 'proposal.md', 'specs/slugify/spec.md'])
        lines = ''.join(f'{DR._sha256(d)}  {p[len(DR.CHANGE_PATH) + 1:]}\n' for p, d in files.items())
        self.assertEqual('sha256:' + DR._sha256(lines.encode('utf-8')), DR.PLANNED_CONTENT)

    def test_the_plan_carries_the_outcome_and_the_adapter_checks_it(self):
        outcome = 'outcome:6a1f0e2d-3c4b-4a59-8d7e-0f1e2d3c4b5a@' + 'a' * 40
        plan = DR.plan(outcome)
        self.assertEqual(plan['change'], DR.CHANGE)
        self.assertEqual(plan['tasks'], [dict(DR.TASK, outcome=outcome)])
        self.assertEqual(P.load_plan(plan)['tasks'][0]['outcome'], outcome)
        for bad in ('outcome:O1', '6a1f0e2d-3c4b-4a59-8d7e-0f1e2d3c4b5a',
                    'outcome:6A1F0E2D-3C4B-4A59-8D7E-0F1E2D3C4B5A'):
            with self.subTest(outcome=bad):
                refused(self, 'OUTCOME_REF_INVALID', DR.plan, bad)


class DemoTests(unittest.TestCase):
    """The initial content's own tests pass, offline, as the D1 command runs them."""

    def test_python_m_unittest_discover_s_tests_passes(self):
        with tempfile.TemporaryDirectory(prefix='aieh-demo-') as tmp:
            fx.write(tmp, DR.template_files())
            env = {k: v for k, v in os.environ.items() if not k.startswith('PYTHON')}
            env['PYTHONDONTWRITEBYTECODE'] = '1'
            result = subprocess.run([sys.executable, '-B', '-m', 'unittest', 'discover', '-s', 'tests'], cwd=tmp,
                                    capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Ran 1 test', result.stderr)
        self.assertTrue(result.stderr.rstrip().endswith('OK'), result.stderr)


class Clone(unittest.TestCase):
    """A throwaway bare repository standing in for the host Gitea, holding the host's initialization commit (a root
    commit with a README, as Gitea's auto-init makes), and a clone of it named aieh-d1-demo."""

    def setUp(self):
        fx.require_repository_access()
        self.root = Path(tempfile.mkdtemp(prefix='aieh-demo-'))
        self.addCleanup(fx.rmtree, self.root)
        ceiling = fx.ceiling(self.root)
        ceiling.start()
        self.addCleanup(ceiling.stop)
        self.remote = self.root / 'gitea' / 'aieh-d1-demo.git'
        self.remote.parent.mkdir()
        fx.git(self.root, 'init', '--quiet', '--bare', '-b', 'main', str(self.remote))
        init = self.root / 'init'
        fx.git(self.root, 'clone', '--quiet', str(self.remote), str(init))
        fx.write(init, {'README.md': INIT_README})
        self.initial = fx.commit_all(init, 'Initial commit')
        fx.git(init, 'push', '--quiet', 'origin', 'main')
        self.project = self.clone('aieh-d1-demo')

    def clone(self, name):
        target = self.root / name
        fx.git(self.root, 'clone', '--quiet', '-c', 'core.autocrlf=false', str(self.remote), str(target))
        return target

    def head(self, repo=None):
        return fx.head(repo or self.project)

    def blob_id(self, data):
        """The id git gives DATA as a blob, its bytes unfiltered."""
        path = self.root / 'blob'
        path.write_bytes(data)
        return fx.git(self.project, 'hash-object', '--no-filters', str(path))

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        code = DR.main(list(argv), out=out, err=err)
        return code, (json.loads(out.getvalue()) if out.getvalue() else None), err.getvalue()


class SeedAndPlace(Clone):
    def test_seed_writes_the_initial_content_on_the_initialization_commit_once(self):
        result = DR.seed(self.project, IDENTITY)
        self.assertEqual((result['result'], result['parent'], result['replaced']),
                         ('committed', self.initial, ['README.md']))
        self.assertEqual(self.head(), result['commit'])
        for path, data in DR.template_files().items():
            self.assertEqual(fx.git(self.project, 'rev-parse', f'{result["commit"]}:{path}'), self.blob_id(data), path)
            self.assertEqual((self.project / path).read_bytes(), data, path)
        self.assertEqual(fx.git(self.project, 'status', '--porcelain', '--untracked-files=all'), '')
        again = DR.seed(self.project, IDENTITY)
        self.assertEqual((again['result'], again['commit']), ('already present', result['commit']))

    def test_seed_never_overwrites_a_later_commit(self):
        DR.seed(self.project, IDENTITY)
        fx.write(self.project, {'README.md': b'changed\n'})
        changed = fx.commit_all(self.project, 'a later change')
        error = refused(self, 'CONTENT_DIFFERS', DR.seed, self.project, IDENTITY)
        self.assertEqual(error.details['paths'], ['README.md'])
        self.assertEqual(self.head(), changed)

    def test_an_empty_repository_is_refused(self):
        empty = self.root / 'empty'
        fx.git(self.root, 'init', '--quiet', '-b', 'main', str(empty))
        refused(self, 'PROJECT_EMPTY', DR.seed, empty, IDENTITY)
        refused(self, 'PROJECT_UNAVAILABLE', DR.seed, self.root / 'missing', IDENTITY)

    def test_place_is_byte_for_byte_and_its_content_is_planning_s(self):
        seeded = DR.seed(self.project, IDENTITY)['commit']
        result = DR.place(self.project, IDENTITY)
        self.assertEqual((result['result'], result['parent'], result['content'], result['identical']),
                         ('committed', seeded, DR.PLANNED_CONTENT, True))
        for path, data in DR.design_files().items():
            self.assertEqual(fx.git(self.project, 'rev-parse', f'{result["commit"]}:{path}'),
                             self.blob_id(data), path)
        again = DR.place(self.project, IDENTITY)
        self.assertEqual((again['result'], again['commit'], again['identical']),
                         ('already present', result['commit'], True))
        report = DR.placement_report(self.project, result['commit'])
        self.assertEqual((report['identical'], report['differs'], report['added'], report['missing']),
                         (True, [], [], []))
        self.assertEqual(self.cli('verify-placement', '--project', str(self.project), '--commit',
                                  result['commit'])[0], 0)

    def test_a_changed_change_folder_is_refused_never_overwritten(self):
        DR.seed(self.project, IDENTITY)
        placed = DR.place(self.project, IDENTITY)['commit']
        fx.write(self.project, {f'{DR.CHANGE_PATH}/notes.md': b'an added file\n'})
        added = fx.commit_all(self.project, 'an added file')
        error = refused(self, 'PLACEMENT_DIFFERS', DR.place, self.project, IDENTITY)
        self.assertEqual(error.details['added'], ['notes.md'])
        self.assertEqual(self.head(), added)
        code, report, _ = self.cli('verify-placement', '--project', str(self.project), '--commit', added)
        self.assertEqual((code, report['identical'], report['added']), (1, False, ['notes.md']))
        self.assertEqual(DR.placement_report(self.project, placed)['identical'], True)

    def test_a_placement_whose_content_is_not_planning_s_changes_nothing(self):
        seeded = DR.seed(self.project, IDENTITY)['commit']
        tampered = dict(DR.design_files())
        tampered[f'{DR.CHANGE_PATH}/design.md'] += b'\n'
        with mock.patch.object(DR, 'design_files', return_value=tampered):
            error = refused(self, 'PLACEMENT_CONTENT_MISMATCH', DR.place, self.project, IDENTITY)
        self.assertNotEqual(error.details['content'], DR.PLANNED_CONTENT)
        self.assertEqual(self.head(), seeded)
        self.assertEqual(fx.git(self.project, 'status', '--porcelain', '--untracked-files=all'), '')
        self.assertFalse((self.project / DR.CHANGE_PATH).exists())

    def test_the_command_line(self):
        code, report, _ = self.cli('files')
        self.assertEqual((code, list(report['template']), report['design']['planned_content']),
                         (0, EXPECTED_TEMPLATE, DR.PLANNED_CONTENT))
        code, result, _ = self.cli('seed', '--project', str(self.project), '--identity', IDENTITY)
        self.assertEqual((code, result['result']), (0, 'committed'))
        code, result, err = self.cli('seed', '--project', str(self.project), '--identity', 'no email')
        self.assertEqual((code, result), (2, None))
        self.assertIn('IDENTITY_INVALID', err)
        code, result, _ = self.cli('place', '--project', str(self.project), '--identity', IDENTITY)
        self.assertEqual((code, result['content']), (0, DR.PLANNED_CONTENT))
        out = self.root / 'plan.json'
        code, result, _ = self.cli('plan', '--outcome', 'outcome:6a1f0e2d-3c4b-4a59-8d7e-0f1e2d3c4b5a', '--out',
                                   str(out))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.read_text(encoding='utf-8'))['tasks'][0]['key'], DR.TASK['key'])
        code, result, err = self.cli('plan', '--outcome', 'outcome:6a1f0e2d-3c4b-4a59-8d7e-0f1e2d3c4b5a', '--out',
                                     str(out))
        self.assertEqual((code, result), (2, None))
        self.assertIn('OUT_UNWRITABLE', err)


class Statement(unittest.TestCase):
    def test_the_owner_s_words_are_admitted_at_this_checkout_s_committed_head(self):
        # Read only: the log at this checkout's HEAD (on main), as record-from-log reads it.
        said = DR.statement()
        self.assertEqual(said, {'text': DR.STATEMENT_TEXT, 'attributedTo': 'owner', 'channel': 'main-session',
                                'reference': DR.STATEMENT_REFERENCE})
        self.assertEqual(A.D.statement_verdict(said), (None, ''))  # an Owner's statement, well formed
        self.assertIn('aieh-d1-demo:', DR.STATEMENT_TEXT.split())  # the repository, as a whole token
        with mock.patch.object(DR, 'STATEMENT_TEXT', DR.STATEMENT_TEXT.replace('small', 'large')):
            refused(self, 'STATEMENT_OUTSIDE_VERBATIM', DR.statement)


class Rehearsal(Clone):
    """The Work records sequence, offline, Backlog.md as the fake: seed, place, the Owner's acceptance from his
    recorded statement, the task at the recorder's commit carrying the outcome, all pushed to the stand-in; then a
    fresh clone in which the pointers and the outcome resolve."""

    def backlog(self, project):
        return P.Backlog(FAKE_BACKLOG, project, runner=fake_backlog.InProcessRunner(FAKE_BACKLOG))

    def work_records(self, backlog, openspec=None):
        DR.seed(self.project, IDENTITY)
        placed = DR.place(self.project, IDENTITY)['commit']
        fx.git(self.project, 'push', '--quiet', 'origin', 'main')
        recorded = A.record_from_log(self.project, DR.CHANGE, 'O1', DR.statement(), recorded_by=RECORDED_BY,
                                     identity=IDENTITY)
        accepted = recorded['commit']
        self.assertEqual(fx.git(self.project, 'rev-parse', f'{accepted}^'), placed)
        self.assertEqual(recorded['decision']['recorded']['about'], {'name': 'aieh-d1-demo', 'as': 'repository'})
        diff = DR.placement_report(self.project, accepted)
        self.assertEqual((diff['identical'], diff['differs'], diff['missing']),
                         (False, ['.openspec.yaml', 'proposal.md'], []))
        self.assertEqual([p.split('/')[0] for p in diff['added']], ['owner-decisions'])
        plan = DR.plan(recorded['reference'])
        created = P.create_tasks(P.Git(self.project), backlog(self.project), plan, accepted, openspec)
        task, = created['tasks']
        self.assertEqual(task['references'][-1], recorded['reference'])
        self.assertTrue(all(P.Pointer.parse(p).revision == accepted for p in task['references'][:-1]))
        return placed, accepted, recorded['reference'], task

    def publish(self, message):
        fx.git(self.project, 'add', '--all')
        fx.git(self.project, 'commit', '--quiet', '-m', message)
        fx.git(self.project, 'push', '--quiet', 'origin', 'main')
        return self.head()

    def check_fresh(self, fresh, accepted, reference, task_id, backlog):
        report = P.resolve_tasks(P.Git(fresh), backlog(fresh), [task_id])
        self.assertTrue(report[0]['pointers'] and all(p['resolved'] for p in report[0]['pointers']), report)
        resolver = A.R.ObjectiveResolver(fresh)
        answer = resolver.resolve(A.L.parse(reference))
        self.assertTrue(answer.resolved, answer)
        self.assertEqual((answer.observed_revision, answer.facts['item']), (accepted, 'O1'))
        content, _ = DR._input_recorder().read_design(fresh, DR.REPOSITORY, DR.CHANGE, accepted)
        self.assertTrue(content.startswith('sha256:'))

    def test_the_sequence_on_a_stand_in_for_the_host_gitea(self):
        placed, accepted, reference, task = self.work_records(self.backlog)
        tip = self.publish('Backlog.md (the fake): the task of add-slugify')
        self.assertEqual(fx.git(self.project, 'rev-parse', f'{tip}^'), accepted)
        fresh = self.clone('fresh')
        self.assertEqual(self.head(fresh), tip)
        self.check_fresh(fresh, accepted, reference, task['id'], self.backlog)
        self.assertEqual(DR.placement_report(fresh, placed)['identical'], True)


@unittest.skipUnless(os.environ.get('AIEH_BACKLOG') and os.environ.get('AIEH_OPENSPEC'),
                     'set AIEH_BACKLOG and AIEH_OPENSPEC to the pinned tools\' entry points')
class LiveRehearsal(Rehearsal):
    """The same sequence with the pinned Backlog.md 1.55.3 and OpenSpec 1.16.0, plus Backlog.md's readiness."""
    category = 'e2e'

    def setUp(self):
        super().setUp()
        home = self.root / 'home'
        home.mkdir()
        env = mock.patch.dict(os.environ, fx.isolated_env(home))
        env.start()
        self.addCleanup(env.stop)
        self.backlog_argv = P.tool_argv(os.environ['AIEH_BACKLOG'])
        self.openspec_argv = P.tool_argv(os.environ['AIEH_OPENSPEC'])

    def real_backlog(self, project):
        return P.Backlog(self.backlog_argv, project)

    def test_the_sequence_on_a_stand_in_for_the_host_gitea(self):
        placed, accepted, reference, task = self.work_records(self.real_backlog, self.openspec_argv)
        self.assertEqual(fx.git(self.project, 'status', '--porcelain', '--untracked-files=all').count('backlog/'), 1)
        tip = self.publish('Backlog.md: the task of add-slugify (plan leaf E-05.1)')
        fresh = self.clone('fresh')
        self.check_fresh(fresh, accepted, reference, task['id'], self.real_backlog)
        readiness = _load('planning_readiness', REPO / 'integrations' / 'planning' / 'planning_readiness.py')
        report = readiness.read_readiness(self.real_backlog(fresh), P.Git(fresh))
        self.assertEqual(report['eligible'], [task['id']])
        self.assertEqual(self.head(fresh), tip)


if __name__ == '__main__':
    unittest.main()
