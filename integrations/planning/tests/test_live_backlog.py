"""Live tests of the planning adapter against the pinned Backlog.md and OpenSpec (P-02.1).

They run only when both tools are named:

    AIEH_BACKLOG=<...>/node_modules/backlog.md/cli.js
    AIEH_OPENSPEC=<...>/node_modules/@fission-ai/openspec/bin/openspec.js

installed from composition/lock/npm with ``npm ci --ignore-scripts`` in a directory
outside the checkout (integrations/planning/README.md). Otherwise every test here is
skipped with that reason, so the basic tier needs neither tool. Each test builds its
own throwaway project repository and per-user directories under a temporary
directory, and never runs Backlog.md or OpenSpec in this checkout.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import two_task_fixture as fx  # noqa: E402

adapter = fx.adapter
BACKLOG = os.environ.get('AIEH_BACKLOG')
OPENSPEC = os.environ.get('AIEH_OPENSPEC')
SKIP = 'set AIEH_BACKLOG and AIEH_OPENSPEC to the pinned Backlog.md 1.55.3 and OpenSpec 1.16.0 entry points'


@unittest.skipUnless(BACKLOG and OPENSPEC, SKIP)
class LiveTwoTask(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.backlog_argv = adapter.tool_argv(BACKLOG)
        cls.openspec_argv = adapter.tool_argv(OPENSPEC)

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-planning-live-'))
        self.addCleanup(fx.rmtree, self.tmp)
        (self.tmp / 'home').mkdir()
        env = mock.patch.dict(os.environ, fx.isolated_env(self.tmp / 'home'))
        env.start()
        self.addCleanup(env.stop)

    def backlog(self, *args):
        return fx.run_tool([*self.backlog_argv, *args], self.repo)

    def statuses(self):
        listed = json.loads(self.backlog('task', 'list', '--json'))
        return {t['id']: t['status'] for t in listed['tasks']}

    def capture(self):
        self.repo, self.commit, data = fx.live_capture(self.backlog_argv, self.openspec_argv, self.tmp)
        self.git = adapter.Git(self.repo)
        return data

    def test_pinned_versions(self):
        self.assertEqual(fx.tool_version(self.backlog_argv, self.tmp), fx.BACKLOG_VERSION)
        self.assertEqual(fx.tool_version(self.openspec_argv, self.tmp), fx.OPENSPEC_VERSION)

    def test_regenerated_capture_equals_the_recorded_fixture(self):
        data = self.capture()
        recorded = fx.recorded()
        self.assertEqual(sorted(data), sorted(recorded))
        for name in sorted(data):
            self.assertEqual(data[name], recorded[name], name)
            self.assertIsNone(fx.MACHINE_PATH.search(fx.dumps(data[name])), name)

    def test_new_design_revision_does_not_touch_backlog_status(self):
        data = self.capture()
        # Backlog.md's own status operation, standing in for the agent doing the work.
        self.backlog('task', 'edit', 'TASK-1', '-s', 'In Progress', '--plain')
        self.assertEqual(self.statuses(), {'TASK-1': 'In Progress', 'TASK-2': 'To Do'})
        design = self.repo / f'openspec/changes/{fx.CHANGE}/design.md'
        design.write_bytes(design.read_bytes() + b'\nA later revision of the design.\n')
        newer = fx.commit_all(self.repo, 'revise design', '2026-11-08T00:00:00Z')
        # The tasks still name, and resolve, the revision they were planned from.
        report = adapter.resolve_tasks(self.git, adapter.Backlog(self.backlog_argv, self.repo))
        self.assertTrue(all(p['resolved'] for t in report for p in t['pointers']), report)
        self.assertEqual({adapter.Pointer.parse(p['pointer']).revision for t in report for p in t['pointers']},
                         {self.commit})
        # The new revision has a different digest: revalidation is visible, not silent.
        old = adapter.Pointer.parse(data['create-result.json']['tasks'][0]['references'][0])
        new = adapter.make_pointer(self.git, fx.CHANGE, 'design.md', newer)
        self.assertNotEqual(old.digest, new.digest)
        # Neither the new revision nor the adapter changed any Backlog.md status.
        self.assertEqual(self.statuses(), {'TASK-1': 'In Progress', 'TASK-2': 'To Do'})
        state = adapter.check_change(self.git, fx.CHANGE, newer, self.openspec_argv)
        self.assertEqual((state['openspec']['taskTrackingConfigured'], state['openspec']['tasks']), (False, []))

    def test_checklist_in_the_change_is_refused(self):
        self.capture()
        fx.write(self.repo, {f'openspec/changes/{fx.CHANGE}/tasks.md': b'## 1. Work\n\n- [ ] 1.1 Measure\n'})
        newer = fx.commit_all(self.repo, 'add a duplicate checklist', '2026-11-08T00:00:00Z')
        plan = json.loads(fx.PLAN.read_text(encoding='utf-8'))
        with self.assertRaises(adapter.PlanningError) as ctx:
            adapter.create_tasks(self.git, adapter.Backlog(self.backlog_argv, self.repo), plan, newer,
                                 self.openspec_argv)
        self.assertEqual(ctx.exception.code, 'OPENSPEC_CHECKLIST_PRESENT')
        self.assertEqual(sorted(self.statuses()), ['TASK-1', 'TASK-2'])

    def test_broken_pointers_fail_visibly(self):
        data = self.capture()
        good = data['create-result.json']['tasks'][0]['references'][0]
        pointer = adapter.Pointer.parse(good)
        broken = {
            'POINTER_DIGEST_MISMATCH': good.replace(pointer.digest, '0' * 64),
            'POINTER_REVISION_MISSING': good.replace(self.commit, 'f' * 40),
            'POINTER_ARTIFACT_MISSING': good.replace('/design.md@', '/missing.md@'),
        }
        for code, text in broken.items():
            with self.subTest(code=code):
                # Backlog.md's own reference edit, as an agent or a person could make it.
                self.backlog('task', 'edit', 'TASK-1', '--ref', text, '--plain')
                report = adapter.resolve_tasks(self.git, adapter.Backlog(self.backlog_argv, self.repo),
                                               ['TASK-1'])
                self.assertEqual([(p['pointer'], p.get('code')) for p in report[0]['pointers']], [(text, code)])
                result = subprocess.run(
                    [sys.executable, '-I', '-B', str(fx.PLANNING / 'planning_adapter.py'), 'resolve',
                     '--project', str(self.repo), '--backlog', BACKLOG, '--task', 'TASK-1'],
                    capture_output=True, text=True, encoding='utf-8', timeout=fx.WAIT_CEILING_S)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(f'FAIL TASK-1 {text}: {code}', result.stderr)



@unittest.skipUnless(BACKLOG and OPENSPEC, SKIP)
class LiveReadiness(unittest.TestCase):
    """P-02.2: Backlog.md's readiness, regenerated in the three recorded stages."""

    def setUp(self):
        import readiness_fixture as rf
        self.rf = rf
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-readiness-live-'))
        self.addCleanup(fx.rmtree, self.tmp)
        self.backlog_argv = adapter.tool_argv(BACKLOG)
        self.repo, self.stages = rf.live_stages(self.backlog_argv, adapter.tool_argv(OPENSPEC), self.tmp)

    def test_regenerated_stages_equal_the_recorded_fixtures(self):
        for stage in self.rf.STAGES:
            recorded = self.rf.recorded(stage)
            self.assertEqual(sorted(self.stages[stage]), sorted(recorded), stage)
            for name in sorted(recorded):
                self.assertEqual(self.stages[stage][name], recorded[name], f'{stage}/{name}')

    def test_command_line_fails_visibly_on_the_missing_dependency(self):
        env = mock.patch.dict(os.environ, fx.isolated_env(self.tmp / 'home'))
        env.start()
        self.addCleanup(env.stop)
        result = subprocess.run(
            [sys.executable, '-I', '-B', str(fx.PLANNING / 'planning_readiness.py'), '--project', str(self.repo),
             '--backlog', BACKLOG], capture_output=True, text=True, encoding='utf-8', timeout=fx.WAIT_CEILING_S)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stderr.strip(), 'FAIL TASK-3: MISSING_DEPENDENCIES TASK-2')
        self.assertEqual(json.loads(result.stdout)['eligible'], [])


if __name__ == '__main__':
    unittest.main()
