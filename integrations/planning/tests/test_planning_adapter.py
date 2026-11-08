"""Tests for integrations/planning/planning_adapter.py (stdlib unittest, plan leaf P-02.1).

Run from the repository root:

    python -I -B -m unittest discover -s integrations/planning/tests -v

These tests need git only. Backlog.md is replaced by fake_backlog.py and OpenSpec by
fake_openspec.py, so they check the adapter's own logic: pointer construction and
re-resolution, the visible failures, the refusal to carry a status, and the refusal of
an OpenSpec change with its own implementation checklist. The committed two-task
capture is re-checked against a freshly built design repository. The live tests
against the pinned Backlog.md and OpenSpec are in test_live_backlog.py.
"""
import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

CATEGORY = 'integration'

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import two_task_fixture as fx  # noqa: E402

adapter = fx.adapter
PlanningError = adapter.PlanningError
FAKE_BACKLOG = [sys.executable, '-I', '-B', str(HERE / 'fake_backlog.py')]
FAKE_OPENSPEC = [sys.executable, '-I', '-B', str(HERE / 'fake_openspec.py')]
DESIGN = f'openspec/changes/{fx.CHANGE}/design.md'


def walk_keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from walk_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk_keys(item)


class RepoCase(unittest.TestCase):
    """A fresh design repository (the two-task fixture's) per test."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-planning-test-'))
        self.addCleanup(fx.rmtree, self.tmp)
        self.repo = self.tmp / 'project'
        self.commit = fx.build_repo(self.repo)
        self.git = adapter.Git(self.repo)
        self.plan = json.loads(fx.PLAN.read_text(encoding='utf-8'))

    def commit_files(self, files, message='change', date='2026-11-08T00:00:00Z'):
        fx.write(self.repo, files)
        return fx.commit_all(self.repo, message, date)

    def expect(self, code, func, *args, **kwargs):
        with self.assertRaises(PlanningError) as ctx:
            func(*args, **kwargs)
        self.assertEqual(ctx.exception.code, code, ctx.exception.message)
        return ctx.exception

    def backlog(self, mode=''):
        env = mock.patch.dict(os.environ, {'FAKE_BACKLOG_MODE': mode})
        env.start()
        self.addCleanup(env.stop)
        return adapter.Backlog(FAKE_BACKLOG, self.repo)

    def backlog_argv(self):
        log = self.repo / '.fake-backlog-argv.jsonl'
        return [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()] if log.exists() else []


class PointerFormat(unittest.TestCase):
    category = 'unit'

    GOOD = ('openspec:changes/qual-02-search-freshness/specs/a/spec.md@' + 'a' * 40 + '#sha256=' + 'b' * 64)

    def test_round_trip(self):
        pointer = adapter.Pointer.parse(self.GOOD)
        self.assertEqual(pointer.text, self.GOOD)
        self.assertEqual(pointer.repo_path, 'openspec/changes/qual-02-search-freshness/specs/a/spec.md')
        self.assertEqual(adapter.Pointer.parse(self.GOOD.replace('a' * 40, 'c' * 64)).revision, 'c' * 64)

    def test_malformed_pointers_are_refused(self):
        bad = [
            self.GOOD.replace('a' * 40, 'a' * 12),                 # abbreviated commit
            self.GOOD.replace('a' * 40, 'A' * 40),                 # not canonical
            self.GOOD.replace('#sha256=' + 'b' * 64, ''),          # no digest
            self.GOOD.replace('b' * 64, 'b' * 63),                 # short digest
            self.GOOD.replace('specs/a/', 'specs/../'),            # not normal
            self.GOOD.replace('specs/a/', './specs/a/'),
            self.GOOD.replace('spec.md', '.hidden'),
            self.GOOD.replace('specs/a/', '/specs/a/'),            # absolute
            self.GOOD.replace('specs/a/', 'specs/a,b/'),           # Backlog splits on commas
            self.GOOD.replace('specs/a/', 'specs/a b/'),
            self.GOOD.replace('openspec:', 'openspec://'),
            self.GOOD.replace('qual-02', 'Qual_02'),
            'backlog:TASK-1', '', None,
        ]
        for text in bad:
            with self.subTest(text=text):
                with self.assertRaises(PlanningError) as ctx:
                    adapter.Pointer.parse(text)
                self.assertEqual(ctx.exception.code, 'POINTER_MALFORMED')

    def test_a_trailing_newline_is_refused(self):
        # Python's $ also matches before a final newline: each grammar is checked whole.
        for text in (self.GOOD + '\n', self.GOOD + '\r\n', '\n' + self.GOOD):
            with self.subTest(text=text):
                with self.assertRaises(PlanningError) as ctx:
                    adapter.Pointer.parse(text)
                self.assertEqual(ctx.exception.code, 'POINTER_MALFORMED')
        for change, artifact in (('qual-02\n', 'design.md'), ('qual-02', 'design.md\n')):
            with self.subTest(change=change, artifact=artifact):
                with self.assertRaises(PlanningError) as ctx:
                    adapter.make_pointer(None, change, artifact, 'a' * 40)  # refused before git
                self.assertEqual(ctx.exception.code, 'POINTER_MALFORMED')

    def test_a_task_id_with_a_trailing_newline_is_refused_before_backlog_runs(self):
        backlog = adapter.Backlog(['backlog'], Path('.'))
        with mock.patch.object(backlog, '_json', side_effect=AssertionError('backlog was run')):
            for task_id in ('TASK-1\n', 'TASK-1\r\n', '\nTASK-1'):
                with self.subTest(task_id=task_id):
                    with self.assertRaises(PlanningError) as ctx:
                        backlog.view(task_id)
                    self.assertEqual(ctx.exception.code, 'TASK_ID_INVALID')


class PointerResolution(RepoCase):
    def test_pointer_names_the_commit_and_the_blob_digest(self):
        pointer = adapter.make_pointer(self.git, fx.CHANGE, 'design.md', self.commit)
        self.assertEqual(pointer.revision, self.commit)
        self.assertEqual(len(self.commit), 40)
        self.assertEqual(pointer.digest, hashlib.sha256((fx.FIXTURE / 'design.md').read_bytes()).hexdigest())
        self.assertEqual(adapter.resolve_pointer(self.git, pointer.text), pointer)

    def test_pointer_resolves_the_revision_not_the_working_tree(self):
        old = adapter.make_pointer(self.git, fx.CHANGE, 'design.md', self.commit)
        newer = self.commit_files({DESIGN: b'## Context\n\nA later design revision.\n'})
        new = adapter.make_pointer(self.git, fx.CHANGE, 'design.md', newer)
        self.assertNotEqual(old.digest, new.digest)
        (self.repo / DESIGN).write_bytes(b'uncommitted edit\n')
        self.assertEqual(adapter.resolve_pointer(self.git, old.text), old)
        self.assertEqual(adapter.resolve_pointer(self.git, new.text), new)

    def test_missing_revision_fails_visibly(self):
        newer = self.commit_files({DESIGN: b'## Context\n\nRewritten away later.\n'})
        pointer = adapter.make_pointer(self.git, fx.CHANGE, 'design.md', newer).text
        # History rewritten: the commit is gone from the repository.
        fx.git(self.repo, 'reset', '--quiet', '--hard', self.commit)
        fx.git(self.repo, 'reflog', 'expire', '--expire=now', '--all')
        fx.git(self.repo, 'gc', '--quiet', '--prune=now')
        error = self.expect('POINTER_REVISION_MISSING', adapter.resolve_pointer, self.git, pointer)
        self.assertIn(newer, error.message)
        never = pointer.replace(newer, '0' * 40)
        self.expect('POINTER_REVISION_MISSING', adapter.resolve_pointer, self.git, never)

    def test_digest_mismatch_fails_visibly(self):
        pointer = adapter.make_pointer(self.git, fx.CHANGE, 'design.md', self.commit)
        forged = pointer.text.replace(pointer.digest, hashlib.sha256(b'other').hexdigest())
        error = self.expect('POINTER_DIGEST_MISMATCH', adapter.resolve_pointer, self.git, forged)
        self.assertEqual(error.details['actual'], pointer.digest)

    def test_missing_artifact_fails_visibly(self):
        # Present only at a later revision, so missing at the pointer's revision.
        newer = self.commit_files({f'openspec/changes/{fx.CHANGE}/notes.md': b'later\n'})
        later = adapter.make_pointer(self.git, fx.CHANGE, 'notes.md', newer)
        self.expect('POINTER_ARTIFACT_MISSING', adapter.resolve_pointer, self.git,
                    later.text.replace(newer, self.commit))
        self.expect('POINTER_ARTIFACT_MISSING', adapter.make_pointer, self.git, fx.CHANGE,
                    'notes.md', self.commit)
        # A directory is not an artifact.
        self.expect('POINTER_ARTIFACT_MISSING', adapter.make_pointer, self.git, fx.CHANGE, 'specs',
                    self.commit)

    def test_revision_arguments_are_checked(self):
        self.assertEqual(self.git.commit('main'), self.commit)
        self.assertIsNone(self.git.commit('no-such-branch'))
        for bad in ('--all', 'a b', ''):
            self.expect('REVISION_INVALID', self.git.commit, bad)


class OpenSpecChecklist(RepoCase):
    def test_fixture_change_is_untracked(self):
        state = adapter.check_change(self.git, fx.CHANGE, self.commit)
        self.assertEqual(state, {'schema': 'intent-driven', 'schema_in_repository': True,
                                 'static_tracking': 'untracked'})

    def test_catalog_schema_declares_no_tracks(self):
        text = (fx.SCHEMA / 'schema.yaml').read_text(encoding='utf-8')
        self.assertEqual(adapter.schema_tracking(text), 'untracked')
        self.assertEqual(adapter.schema_tracking(text.replace('apply:\n', 'apply:\n  tracks: tasks.md\n')),
                         'tracked')
        self.assertEqual(adapter.schema_tracking(text.replace('apply:\n', 'apply:\n  tracks: null\n')),
                         'untracked')
        self.assertEqual(adapter.schema_tracking('name: x\n'), 'unknown')
        self.assertEqual(adapter.schema_tracking('apply: {tracks: tasks.md}\n'), 'unknown')

    def test_change_with_a_checklist_is_refused_before_backlog_is_used(self):
        newer = self.commit_files({f'openspec/changes/{fx.CHANGE}/tasks.md': b'- [ ] 1.1 Measure\n'})
        backlog = self.backlog()
        error = self.expect('OPENSPEC_CHECKLIST_PRESENT', adapter.create_tasks, self.git, backlog,
                            self.plan, newer)
        self.assertEqual(error.details['files'], [f'openspec/changes/{fx.CHANGE}/tasks.md'])
        self.assertEqual(self.backlog_argv(), [])

    def test_schema_that_tracks_tasks_is_refused(self):
        path = 'openspec/schemas/intent-driven/schema.yaml'
        text = (self.repo / path).read_text(encoding='utf-8').replace('apply:\n', 'apply:\n  tracks: tasks.md\n')
        newer = self.commit_files({path: text.encode('utf-8')})
        self.expect('OPENSPEC_TRACKING_CONFIGURED', adapter.check_change, self.git, fx.CHANGE, newer)

    def test_schema_outside_the_repository_needs_openspec(self):
        fx.git(self.repo, 'rm', '-r', '--quiet', 'openspec/schemas')
        newer = fx.commit_all(self.repo, 'schema from elsewhere', '2026-11-08T00:00:00Z')
        self.expect('OPENSPEC_TRACKING_UNKNOWN', adapter.check_change, self.git, fx.CHANGE, newer)
        state = adapter.check_change(self.git, fx.CHANGE, newer, FAKE_OPENSPEC)
        self.assertIs(state['openspec']['taskTrackingConfigured'], False)
        with mock.patch.dict(os.environ, {'FAKE_OPENSPEC_TRACKED': '1'}):
            self.expect('OPENSPEC_TRACKING_CONFIGURED', adapter.check_change, self.git, fx.CHANGE, newer,
                        FAKE_OPENSPEC)

    def test_openspec_runs_on_the_exact_revision(self):
        # The working tree gains tasks.md, but the revision does not have it.
        (self.repo / f'openspec/changes/{fx.CHANGE}/tasks.md').write_bytes(b'- [ ] 1.1\n')
        state = adapter.check_change(self.git, fx.CHANGE, self.commit, FAKE_OPENSPEC)
        self.assertEqual(state['openspec']['tasks'], [])

    def test_missing_change_fails_visibly(self):
        self.expect('CHANGE_MISSING', adapter.check_change, self.git, 'no-such-change', self.commit)


class PlanInput(unittest.TestCase):
    category = 'unit'

    def setUp(self):
        self.plan = json.loads(fx.PLAN.read_text(encoding='utf-8'))

    def expect(self, code, plan):
        with self.assertRaises(PlanningError) as ctx:
            adapter.load_plan(plan)
        self.assertEqual(ctx.exception.code, code, ctx.exception.message)

    def test_fixture_plan_loads(self):
        self.assertEqual([t['key'] for t in adapter.load_plan(self.plan)['tasks']],
                         ['measure-delay', 'refresh-on-add'])

    def test_status_in_the_plan_is_refused(self):
        for key in sorted(adapter.STATUS_KEYS):
            with self.subTest(key=key):
                plan = json.loads(json.dumps(self.plan))
                plan['tasks'][0][key] = 'Done'
                self.expect('STATUS_NOT_OWNED', plan)
                plan = json.loads(json.dumps(self.plan))
                plan[key] = 'In Progress'
                self.expect('STATUS_NOT_OWNED', plan)

    def test_task_without_a_source_pointer_is_refused(self):
        for artifacts in ([], None, ['design.md', 'design.md']):
            plan = json.loads(json.dumps(self.plan))
            plan['tasks'][1]['artifacts'] = artifacts
            self.expect('POINTER_ABSENT', plan)

    def test_dependencies_name_earlier_tasks(self):
        plan = json.loads(json.dumps(self.plan))
        plan['tasks'][1]['depends_on'] = ['no-such-task']
        self.expect('PLAN_DEPENDENCY_UNKNOWN', plan)
        plan = json.loads(json.dumps(self.plan))
        plan['tasks'][0]['depends_on'] = ['refresh-on-add']  # forward reference (or a cycle)
        self.expect('PLAN_DEPENDENCY_UNKNOWN', plan)

    def test_shape_is_checked(self):
        for mutate in (lambda p: p.update(format='planning-map/v2'),
                       lambda p: p.update(extra=1),
                       lambda p: p.update(change='Not An Id'),
                       lambda p: p.update(tasks=[]),
                       lambda p: p['tasks'][0].update(checklist=['x']),
                       lambda p: p['tasks'][0].update(title=' padded'),
                       lambda p: p['tasks'][0].update(title='two\nlines'),
                       lambda p: p['tasks'][1].update(key='measure-delay')):
            plan = json.loads(json.dumps(self.plan))
            mutate(plan)
            self.expect('PLAN_INVALID', plan)
        self.expect('PLAN_INVALID', [])


class CreateTasks(RepoCase):
    def test_two_tasks_with_pointers_and_a_dependency(self):
        result = adapter.create_tasks(self.git, self.backlog(), self.plan, 'main')
        self.assertEqual(result['revision'], self.commit)
        self.assertEqual([(t['key'], t['id'], t['dependencies']) for t in result['tasks']],
                         [('measure-delay', 'TASK-1', []), ('refresh-on-add', 'TASK-2', ['TASK-1'])])
        for task, planned in zip(result['tasks'], self.plan['tasks']):
            self.assertEqual([adapter.Pointer.parse(p).artifact for p in task['references']],
                             planned['artifacts'])
            for text in task['references']:
                self.assertEqual(adapter.resolve_pointer(self.git, text).revision, self.commit)
        state = json.loads((self.repo / '.fake-backlog.json').read_text(encoding='utf-8'))
        self.assertEqual(state['tasks'][1]['dependencies'], ['TASK-1'])
        self.assertEqual(state['tasks'][1]['references'], result['tasks'][1]['references'])

    def test_no_status_flows_from_the_adapter(self):
        result = adapter.create_tasks(self.git, self.backlog(), self.plan, self.commit)
        self.assertNotIn('status', set(walk_keys(result)))
        calls = self.backlog_argv()
        self.assertEqual({tuple(c[:2]) for c in calls}, adapter.BACKLOG_COMMANDS)
        for call in calls:
            options = call[:call.index('--')] if '--' in call else call
            self.assertFalse([a for a in options if a in ('-s', '--status') or a.startswith('--status=')],
                             call)
        creates = [c for c in calls if c[:2] == ['task', 'create']]
        self.assertEqual(len(creates), 2)
        self.assertIn('--dep=TASK-1', creates[1])

    def test_backlog_wrapper_refuses_other_commands_and_status(self):
        backlog = self.backlog()
        for args in (('task', 'edit', 'TASK-1', '-s', 'Done'), ('init', 'x'), ('task', 'archive', 'TASK-1'),
                     ('task', 'create', '--status=Done', '--', 'x'), ('task', 'create', '-s', 'Done', '--', 'x')):
            with self.subTest(args=args):
                self.expect('ADAPTER_REFUSED', backlog.run, *args)
        # '-s' as the title, after '--', is a title and not an option.
        backlog.run('task', 'create', '--plain', '--', '-s')
        self.assertEqual(backlog.list_tasks()[0]['title'], '-s')

    def test_duplicate_mapping_is_refused(self):
        adapter.create_tasks(self.git, self.backlog(), self.plan, self.commit)
        before = len(self.backlog_argv())
        self.expect('BACKLOG_DUPLICATE', adapter.create_tasks, self.git, self.backlog(), self.plan, self.commit)
        self.assertFalse([c for c in self.backlog_argv()[before:] if c[:2] == ['task', 'create']])

    def test_readback_mismatch_fails_visibly(self):
        error = self.expect('BACKLOG_MISMATCH', adapter.create_tasks, self.git, self.backlog('drop-refs'),
                            self.plan, self.commit)
        self.assertEqual(error.details['created'], [{'key': 'measure-delay', 'id': 'TASK-1'}])

    def test_partial_failure_reports_what_was_created(self):
        error = self.expect('BACKLOG_FAILED', adapter.create_tasks, self.git, self.backlog('fail-create-2'),
                            self.plan, self.commit)
        self.assertEqual([c['id'] for c in error.details['created']], ['TASK-1'])

    def test_unexpected_envelope_fails_visibly(self):
        self.expect('BACKLOG_OUTPUT', adapter.create_tasks, self.git, self.backlog('bad-envelope'),
                    self.plan, self.commit)

    def test_create_that_leaves_no_new_task_fails_visibly(self):
        self.expect('BACKLOG_OUTPUT', adapter.create_tasks, self.git, self.backlog('lost-create'),
                    self.plan, self.commit)

    def test_missing_revision_or_artifact_creates_nothing(self):
        self.expect('POINTER_REVISION_MISSING', adapter.create_tasks, self.git, self.backlog(), self.plan,
                    '1' * 40)
        plan = json.loads(json.dumps(self.plan))
        plan['tasks'][1]['artifacts'].append('specs/missing/spec.md')
        self.expect('POINTER_ARTIFACT_MISSING', adapter.create_tasks, self.git, self.backlog(), plan,
                    self.commit)
        self.assertFalse([c for c in self.backlog_argv() if c[:2] == ['task', 'create']])


class ResolveTasks(RepoCase):
    def test_resolve_reports_each_pointer_and_missing_provenance(self):
        backlog = self.backlog()
        result = adapter.create_tasks(self.git, backlog, self.plan, self.commit)
        backlog.run('task', 'create', '--ref=https://example.invalid/x', '--plain', '--', 'No design source')
        good = result['tasks'][0]['references'][0]
        broken = good.replace(self.commit, '2' * 40)
        backlog.run('task', 'create', f'--ref={broken}', '--plain', '--', 'Broken pointer')
        report = adapter.resolve_tasks(self.git, backlog)
        by_id = {entry['id']: entry for entry in report}
        self.assertTrue(all(p['resolved'] for p in by_id['TASK-1']['pointers'] + by_id['TASK-2']['pointers']))
        self.assertEqual(by_id['TASK-3']['failure']['code'], 'POINTER_ABSENT')
        self.assertEqual(by_id['TASK-4']['pointers'][0]['code'], 'POINTER_REVISION_MISSING')
        self.assertNotIn('status', set(walk_keys(report)))
        self.assertEqual([f[0] for f in adapter._failures(report)], ['TASK-3', 'TASK-4'])


class CommandLine(RepoCase):
    category = 'contract'

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = adapter.main([str(a) for a in argv])
        return code, out.getvalue(), err.getvalue()

    def test_pointer_and_resolve(self):
        code, out, _ = self.run_main('pointer', '--project', self.repo, '--change', fx.CHANGE,
                                     '--artifact', 'design.md', '--revision', 'main')
        self.assertEqual(code, 0)
        pointer = out.strip()
        self.assertEqual(adapter.Pointer.parse(pointer).revision, self.commit)
        code, out, err = self.run_main('resolve', '--project', self.repo, '--pointer', pointer)
        self.assertEqual((code, err), (0, ''))
        forged = pointer[:-1] + ('0' if pointer[-1] != '0' else '1')
        code, out, err = self.run_main('resolve', '--project', self.repo, '--pointer', forged)
        self.assertEqual(code, 1)
        self.assertIn('POINTER_DIGEST_MISMATCH', err)
        self.assertFalse(json.loads(out)['tasks'][0]['pointers'][0]['resolved'])

    def test_create_through_the_command_line(self):
        plan = self.tmp / 'plan.json'
        shutil.copyfile(fx.PLAN, plan)
        with mock.patch.object(adapter, 'tool_argv', lambda spec: FAKE_BACKLOG if spec == 'fake' else []):
            code, out, err = self.run_main('create', '--project', self.repo, '--plan', plan,
                                           '--revision', 'main', '--backlog', 'fake')
        self.assertEqual(code, 0, err)
        self.assertEqual([t['id'] for t in json.loads(out)['tasks']], ['TASK-1', 'TASK-2'])
        with mock.patch.object(adapter, 'tool_argv', lambda spec: FAKE_BACKLOG):
            code, _, err = self.run_main('create', '--project', self.repo, '--plan', plan,
                                         '--revision', 'main', '--backlog', 'fake')
        self.assertEqual(code, 1)
        self.assertIn('FAIL BACKLOG_DUPLICATE', err)

    def test_could_not_run(self):
        code, _, err = self.run_main('resolve', '--project', self.tmp, '--pointer', 'x')
        self.assertEqual(code, 2)
        self.assertIn('not a git working tree', err)
        code, _, err = self.run_main('resolve', '--project', self.repo)
        self.assertEqual(code, 2)
        code, _, err = self.run_main('create', '--project', self.repo, '--plan', self.tmp / 'absent.json',
                                     '--revision', 'main', '--backlog', 'x')
        self.assertEqual(code, 2)


class RecordedCapture(RepoCase):
    """The committed Backlog.md capture still resolves against a freshly built design repository."""
    category = 'contract'

    def setUp(self):
        super().setUp()
        self.recorded = fx.recorded()

    def test_capture_files(self):
        self.assertEqual(sorted(self.recorded), ['create-result.json', 'task-list.json',
                                                 'task-view-TASK-1.json', 'task-view-TASK-2.json'])
        for path in sorted(fx.RECORDED.glob('*.json')):
            text = path.read_text(encoding='utf-8')
            self.assertIsNone(fx.MACHINE_PATH.search(text), path.name)
            self.assertEqual(text, fx.dumps(json.loads(text)), path.name)

    def test_recorded_pointers_resolve_the_actual_design_revision(self):
        result = self.recorded['create-result.json']
        self.assertEqual(result['revision'], self.commit, 'rebuild the repository inputs or re-record')
        listed = {t['id']: t for t in self.recorded['task-list.json']['tasks']}
        for task, planned in zip(result['tasks'], self.plan['tasks']):
            view = self.recorded[f'task-view-{task["id"]}.json']['task']
            self.assertEqual(view['references'], task['references'])
            self.assertEqual(listed[task['id']]['references'], task['references'])
            self.assertEqual([adapter.Pointer.parse(p).artifact for p in view['references']],
                             planned['artifacts'])
            for text in view['references']:
                pointer = adapter.resolve_pointer(self.git, text)
                self.assertEqual(pointer.revision, self.commit)

    def test_recorded_dependency_and_backlog_owned_status(self):
        view = self.recorded['task-view-TASK-2.json']
        self.assertEqual((view['schemaVersion'], view['kind']), (1, 'task-view'))
        self.assertEqual(view['task']['dependencies'], ['TASK-1'])
        self.assertEqual(view['task']['dependencyGraph']['edges'], [{'from': 'TASK-2', 'to': 'TASK-1'}])
        # Status appears only where Backlog.md itself reports it, never in the adapter's result.
        self.assertNotIn('status', set(walk_keys(self.recorded['create-result.json'])))
        self.assertEqual({t['status'] for t in self.recorded['task-list.json']['tasks']}, {'To Do'})
        openspec = self.recorded['create-result.json']['openspec']['openspec']
        self.assertEqual((openspec['taskTrackingConfigured'], openspec['tasks'], openspec['state']),
                         (False, [], 'ready'))


if __name__ == '__main__':
    unittest.main()
