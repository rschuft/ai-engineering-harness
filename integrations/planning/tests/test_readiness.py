"""Tests for integrations/planning/planning_readiness.py (stdlib unittest, plan leaf P-02.2).

Offline: Backlog.md's recorded readiness JSON (fixtures/readiness/<stage>/) is replayed by
fake_backlog.py (FAKE_BACKLOG_SNAPSHOT), and the source pointers resolve against a freshly
built design repository, so these tests need git only. The live regeneration of the
fixtures is in test_live_backlog.py.
"""
import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

CATEGORY = 'contract'

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import readiness_fixture as rf  # noqa: E402

fx = rf.fx
adapter = rf.adapter
readiness = rf.readiness
FAKE_BACKLOG = [sys.executable, '-I', '-B', str(HERE / 'fake_backlog.py')]


class StatusTrap(dict):
    """A dict that fails the test if a status-like field is read from it."""

    TRAPPED = ('status', 'completed')

    def __getitem__(self, key):
        if key in self.TRAPPED:
            raise AssertionError(f'readiness read {key!r}')
        return super().__getitem__(key)

    def get(self, key, default=None):
        if key in self.TRAPPED:
            raise AssertionError(f'readiness read {key!r}')
        return super().get(key, default)


def trapped(value):
    if isinstance(value, dict):
        return StatusTrap({k: trapped(v) for k, v in value.items()})
    if isinstance(value, list):
        return [trapped(v) for v in value]
    return value


class Stages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='aieh-readiness-test-'))
        cls.repo = cls.tmp / 'project'
        cls.commit = fx.build_repo(cls.repo)
        cls.git = adapter.Git(cls.repo)
        cls.stages = {stage: rf.recorded(stage) for stage in rf.STAGES}

    @classmethod
    def tearDownClass(cls):
        fx.rmtree(cls.tmp)

    def replay(self, stage):
        env = mock.patch.dict(os.environ, {'FAKE_BACKLOG_SNAPSHOT': str(rf.RECORDED / stage)})
        env.start()
        self.addCleanup(env.stop)
        return adapter.Backlog(FAKE_BACKLOG, self.repo)

    def view(self, stage, task_id):
        return copy.deepcopy(self.stages[stage][f'task-view-{task_id}.json']['task'])

    def entry(self, report, task_id):
        return next(t for t in report['tasks'] if t['id'] == task_id)

    def test_recorded_files(self):
        common = ['readiness.json', 'task-list-ready.json', 'task-list.json']
        self.assertEqual(sorted(self.stages['blocked']), common + ['task-view-TASK-1.json', 'task-view-TASK-2.json'])
        self.assertEqual(sorted(self.stages['missing']), common + ['task-view-TASK-1.json', 'task-view-TASK-3.json'])

    def test_eligible_equals_backlogs_own_ready_filter(self):
        # Every pointer resolves here, so eligibility is exactly Backlog.md's `task list --ready`.
        for stage in rf.STAGES:
            with self.subTest(stage=stage):
                ready = [t['id'] for t in self.stages[stage]['task-list-ready.json']['tasks']]
                self.assertEqual(self.stages[stage]['readiness.json']['eligible'], ready)
        for path in sorted(rf.RECORDED.rglob('*.json')):
            text = path.read_text(encoding='utf-8')
            self.assertIsNone(fx.MACHINE_PATH.search(text), path)
            self.assertEqual(text, fx.dumps(json.loads(text)), path)

    def test_replayed_backlog_json_gives_the_recorded_report(self):
        for stage in rf.STAGES:
            with self.subTest(stage=stage):
                report = readiness.read_readiness(self.replay(stage), self.git)
                self.assertEqual(report, self.stages[stage]['readiness.json'])

    def test_blocked_chain_stays_ineligible(self):
        report = self.stages['blocked']['readiness.json']
        task2 = self.entry(report, 'TASK-2')
        self.assertFalse(task2['eligible'])
        self.assertEqual(task2['reasons'], [readiness.BLOCKED])
        self.assertEqual(task2['blocking_dependencies'], ['TASK-1'])
        self.assertEqual(task2['missing_dependencies'], [])
        self.assertEqual(report['eligible'], ['TASK-1'])
        # Backlog.md's own words, unchanged.
        self.assertEqual(task2['backlog_readiness'], self.view('blocked', 'TASK-2')['readiness'])

    def test_completed_dependency_unblocks(self):
        report = self.stages['unblocked']['readiness.json']
        self.assertEqual(report['eligible'], ['TASK-2'])
        self.assertEqual(self.entry(report, 'TASK-1')['reasons'], [readiness.NOT_READY])
        # The status change is Backlog.md's own record, made through its CLI by the test.
        self.assertEqual({t['id']: t['status'] for t in self.stages['unblocked']['task-list.json']['tasks']},
                         {'TASK-1': 'Done', 'TASK-2': 'To Do'})

    def test_missing_dependency_is_visible(self):
        report = self.stages['missing']['readiness.json']
        task3 = self.entry(report, 'TASK-3')
        self.assertFalse(task3['eligible'])
        self.assertEqual(task3['reasons'], [readiness.MISSING])
        self.assertEqual(task3['missing_dependencies'], ['TASK-2'])
        self.assertEqual(task3['graph_unresolved'], [{'id': 'TASK-2', 'state': 'missing'}])
        self.assertEqual(report['eligible'], [])
        self.assertEqual(list(readiness.failures(report)), [('TASK-3', 'MISSING_DEPENDENCIES TASK-2')])

    def test_no_status_is_read(self):
        for stage in rf.STAGES:
            listed = {t['id']: t['isReady'] for t in self.stages[stage]['task-list.json']['tasks']}
            for task_id, ready in listed.items():
                with self.subTest(stage=stage, task=task_id):
                    entry = readiness.classify(trapped(self.view(stage, task_id)), ready)
                    self.assertEqual({k: v for k, v in entry.items() if k != 'pointers'},
                                     {k: v for k, v in self.entry(self.stages[stage]['readiness.json'],
                                                                  task_id).items() if k != 'pointers'})

    def test_backlog_verdict_wins_over_statuses(self):
        # Statuses say the dependency is done, but Backlog.md says blocked: still ineligible.
        task = self.view('blocked', 'TASK-2')
        for node in task['dependencyGraph']['nodes']:
            node.update(status='Done', completed=True)
        entry = readiness.classify(task, False)
        self.assertEqual((entry['eligible'], entry['reasons']), (False, [readiness.BLOCKED]))
        # Statuses say the dependency is open, but Backlog.md says ready: Backlog.md decides.
        task = self.view('unblocked', 'TASK-2')
        for node in task['dependencyGraph']['nodes']:
            node.update(status='To Do', completed=False)
        entry = readiness.classify(task, True)
        self.assertEqual((entry['eligible'], entry['reasons']), (True, []))

    def test_absent_or_malformed_fields_are_unknown(self):
        mutations = {
            'no readiness': lambda t: t.pop('readiness'),
            'no isBlocked': lambda t: t['readiness'].pop('isBlocked'),
            'no missingDependencies': lambda t: t['readiness'].pop('missingDependencies'),
            'isReady as text': lambda t: t['readiness'].update(isReady='true'),
            'ids not strings': lambda t: t['readiness'].update(blockingDependencies=[1]),
            'no task isReady': lambda t: t.pop('isReady'),
            'no graph': lambda t: t.pop('dependencyGraph'),
            'node without state': lambda t: t['dependencyGraph']['nodes'][1].pop('state'),
        }
        for name, mutate in mutations.items():
            with self.subTest(name):
                task = self.view('unblocked', 'TASK-2')
                mutate(task)
                entry = readiness.classify(task, True)
                self.assertEqual((entry['eligible'], entry['reasons']), (False, [readiness.UNKNOWN]))
        entry = readiness.classify(self.view('unblocked', 'TASK-2'), None)  # absent from task list
        self.assertEqual(entry['reasons'], [readiness.UNKNOWN])

    def test_backlog_fields_that_disagree_are_inconsistent(self):
        def not_ready_but_flagged(t):
            t['readiness'].update(isReady=False, isBlocked=True)
            t['isReady'] = False

        cases = {
            'list says ready': (lambda t: None, 'blocked', True),
            'view isReady differs': (lambda t: t.update(isReady=True), 'blocked', False),
            'ready yet blocked': (lambda t: t['readiness'].update(isBlocked=True), 'unblocked', True),
            'ready with a missing id': (lambda t: t['readiness'].update(missingDependencies=['TASK-9']),
                                        'unblocked', True),
            'blocked flag without ids': (not_ready_but_flagged, 'unblocked', False),
        }
        for name, (mutate, stage, listed) in cases.items():
            with self.subTest(name):
                task = self.view(stage, 'TASK-2')
                mutate(task)
                entry = readiness.classify(task, listed)
                self.assertFalse(entry['eligible'])
                self.assertIn(readiness.INCONSISTENT, entry['reasons'])
                self.assertIn(('TASK-2', readiness.INCONSISTENT),
                              list(readiness.failures({'tasks': [entry]})))

    def test_failing_or_absent_pointer_is_never_eligible(self):
        backlog = self.replay('unblocked')
        report = readiness.read_readiness(backlog, self.git)
        self.assertEqual(report['eligible'], ['TASK-2'])
        good = self.entry(report, 'TASK-2')['pointers'][0]['pointer']
        broken = good.replace(self.commit, 'e' * 40)
        cases = {'POINTER_REVISION_MISSING': [broken], 'POINTER_ABSENT': [],
                 'POINTER_MALFORMED': ['openspec:changes/x']}
        for code, refs in cases.items():
            with self.subTest(code):
                with tempfile.TemporaryDirectory(prefix='aieh-readiness-snap-') as snap:
                    for name, data in self.stages['unblocked'].items():
                        if name == 'task-view-TASK-2.json':
                            data = copy.deepcopy(data)
                            data['task']['references'] = refs
                        (Path(snap) / name).write_text(json.dumps(data), encoding='utf-8')
                    with mock.patch.dict(os.environ, {'FAKE_BACKLOG_SNAPSHOT': snap}):
                        report = readiness.read_readiness(adapter.Backlog(FAKE_BACKLOG, self.repo), self.git)
                entry = self.entry(report, 'TASK-2')
                self.assertFalse(entry['eligible'])
                self.assertIn(code, entry['reasons'])
                self.assertEqual(report['eligible'], [])
                self.assertIn(('TASK-2', code), list(readiness.failures(report)))
        # Without pointer resolution only Backlog.md's verdict counts.
        self.assertEqual(readiness.read_readiness(self.replay('unblocked'), None)['eligible'], ['TASK-2'])

    def test_readiness_issues_only_reads(self):
        log = self.repo / '.fake-backlog-argv.jsonl'
        if log.exists():
            log.unlink()
        readiness.read_readiness(self.replay('missing'), self.git)
        calls = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
        self.assertEqual(calls, [['task', 'list', '--json'], ['task', 'view', 'TASK-1', '--json'],
                                 ['task', 'view', 'TASK-3', '--json']])

    def run_main(self, stage, *extra):
        out, err = io.StringIO(), io.StringIO()
        env = {'FAKE_BACKLOG_SNAPSHOT': str(rf.RECORDED / stage)}
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(adapter, 'tool_argv', lambda spec: FAKE_BACKLOG), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = readiness.main(['--project', str(self.repo), '--backlog', 'fake', *extra])
        return code, out.getvalue(), err.getvalue()

    def test_command_line_exit_codes(self):
        code, out, err = self.run_main('blocked')
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(json.loads(out)['eligible'], ['TASK-1'])
        code, out, err = self.run_main('unblocked', '--task', 'TASK-2')
        self.assertEqual((code, json.loads(out)['eligible']), (0, ['TASK-2']))
        code, out, err = self.run_main('missing')
        self.assertEqual(code, 1)
        self.assertEqual(err.strip(), 'FAIL TASK-3: MISSING_DEPENDENCIES TASK-2')
        code, out, err = self.run_main('missing', '--task', 'TASK-9')
        self.assertEqual(code, 1)
        self.assertIn('FAIL BACKLOG_FAILED', err)
        with mock.patch.object(adapter, 'tool_argv', lambda spec: FAKE_BACKLOG), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            code = readiness.main(['--project', str(self.tmp), '--backlog', 'fake'])
        self.assertEqual(code, 2)
        self.assertIn('not a git working tree', err.getvalue())


if __name__ == '__main__':
    unittest.main()
