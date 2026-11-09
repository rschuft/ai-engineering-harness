"""One dispatch readiness evaluation is one adapter operation (plan leaf F-09.4, ruling R3).

Run from the repository root:

    python -I -B -m unittest discover -s integrations/dispatch/tests -v

``PlanningWorkSource.read`` lists Backlog.md's tasks and then evaluates the task's readiness,
which lists them again: within one operation Backlog.md answers the list once, every pointer is
resolved through one read session (one opened repository, plan leaf F-10.3), and the session
ends with the read, also when the read raises. The design repository is the planning fixture's
(``two_task_fixture.build_repo``); Backlog.md is its own recorded readiness output, replayed in
this process.
"""
from pathlib import Path
import importlib.util
import os
import sys
import tempfile
import unittest
from unittest import mock

CATEGORY = 'integration'

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PLANNING_TESTS = REPO / 'integrations' / 'planning' / 'tests'
SNAPSHOT = PLANNING_TESTS / 'fixtures' / 'readiness' / 'unblocked'


def _load(name, path):
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


di = _load('dispatch_inputs', HERE.parent / 'dispatch_inputs.py')
planning = di.planning
fx = _load('two_task_fixture', PLANNING_TESTS / 'two_task_fixture.py')
fake_backlog = _load('fake_backlog', PLANNING_TESTS / 'fake_backlog.py')
FAKE_BACKLOG = [sys.executable, '-I', '-B', str(PLANNING_TESTS / 'fake_backlog.py')]


class Recorded(planning._Session):
    """A read session that keeps every instance that opened its repository."""
    made = []

    def _open(self):
        first = self.repository is None and not self.closed
        repository = super()._open()
        if first:
            self.opened = repository
            type(self).made.append(self)
        return repository


class ReadIsOneOperation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='aieh-dispatch-op-'))
        cls.addClassCleanup(fx.rmtree, cls.tmp)
        cls.repo = cls.tmp / 'design'
        fx.build_repo(cls.repo)

    def setUp(self):
        Recorded.made = []
        self.calls = []
        inner = fake_backlog.InProcessRunner(FAKE_BACKLOG)

        def counting(argv, **kwargs):
            self.calls.append(argv[len(FAKE_BACKLOG):])
            return inner(argv, **kwargs)

        for patch in (mock.patch.object(planning, '_Session', Recorded),
                      mock.patch.dict(os.environ, {'FAKE_BACKLOG_SNAPSHOT': str(SNAPSHOT)})):
            patch.start()
            self.addCleanup(patch.stop)
        self.source = di.PlanningWorkSource(planning.Backlog(FAKE_BACKLOG, self.repo, runner=counting),
                                            planning.Git(self.repo))

    def assertEnded(self, count):
        self.assertEqual(len(Recorded.made), count)
        for session in Recorded.made:
            self.assertTrue(session.closed, 'the session is still open')
            self.assertIsNone(session.opened._dul, 'its repository is still open')
        self.assertIsNone(planning.current_operation())

    def test_one_list_one_view_one_reader(self):
        for _ in range(2):
            entry = self.source.read('task-2')
            self.assertEqual(entry['id'], 'TASK-2')
            self.assertTrue(entry['eligible'], entry)
        self.assertEqual(self.calls, [['task', 'list', '--json'], ['task', 'view', 'TASK-2', '--json']] * 2)
        self.assertEnded(2)  # one session per read; nothing kept between the reads

    def test_an_exception_ends_the_reader(self):
        with mock.patch.object(planning.Git, 'blob', side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                self.source.read('TASK-2')
        self.assertEnded(1)


if __name__ == '__main__':
    unittest.main()
