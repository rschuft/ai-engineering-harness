"""Tests for the step 0 rehearsal driver (D1 slice C: ``tests/live_step0_rehearsal.py``), offline.

Run from the repository root, under the tools interpreter (Dulwich is required; Git Bash on Windows):

    <tools python> -I -B -m unittest discover -s integrations/dispatch/tests -p test_step0_rehearsal.py -v

``rehearse`` against a fake guest whose commands SEED, the synthetic edit and RESULT run for real (a real shell and
git over a temporary directory standing for ``/workspace/<repository>``, as ``test_attempt_run``'s oracle runs them)
and whose probes answer as the container would: every step passes, the exclusion paths of both kinds are exercised,
the bundle is pulled and verified by the retained verifier and the host's intake accepts it with the commit-id
equality, RESULT without a delivery makes the same commit, a second delivery is refused; a command above the
argument limit is answered as the shell refuses it; the synthetic tree is the demo's size; the test-only builders are
registered only by the rehearsal.
"""
from pathlib import Path
import importlib.util
import os
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock

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


S0 = _load('live_step0_rehearsal', HERE / 'live_step0_rehearsal.py')
tar, di, AR = S0.tar, S0.di, S0.AR
FIXTURE = {'conversation_id': 'f0420000-0000-4000-8000-000000000f42'}


class FakeContainer:
    """The fixture conversation's container: the dispatcher's commands run for real in WORKSPACE's parent; the
    probes are answered as the pinned image would."""

    def __init__(self, tmp):
        self.tmp, self.workspace, self.exchange = Path(tmp), None, Path(tmp) / 'exchange'
        self.exchange.mkdir()
        self.calls, self.created = [], False

    def transport(self, method, path, body, deliver=None):
        self.calls.append((method, path))
        command = body['command']
        if command.startswith(": '"):
            if len(command.encode()) >= S0.MAX_ARG_STRLEN:
                return {'status': 500, 'body': {'detail': 'Internal Server Error'}}
            size = re.search(r'argv ([0-9]+) ok', command).group(1)
            return {'status': 200, 'body': {'stdout': f'AIEH-STEP0 argv {size} ok\n', 'stderr': '', 'exit_code': 0}}
        if command == S0.PROBES['tools']:
            out = '/usr/bin/git\n/usr/local/bin/python\ngit version 2.47.3\nPython 3.13.0\nPython 3.13.0\n10001\n'
            return {'status': 200, 'body': {'stdout': out, 'stderr': '', 'exit_code': 0}}
        if command == S0.PROBES['line-endings']:
            return {'status': 200, 'body': {'stdout': 'lf\ncrlf\r\nend tRuE ', 'stderr': '', 'exit_code': 0}}
        if command == S0.PROBES['large-output']:
            return {'status': 200, 'body': {'stdout': '0123456789abcdef' * 65536, 'stderr': '', 'exit_code': 0}}
        target = re.search(r"'(/workspace/[a-z0-9-]+)'", command).group(1)
        if self.workspace is None:
            self.workspace = self.tmp / 'ws' / target.rsplit('/', 1)[1]
            self.workspace.parent.mkdir()
        rc, out, err = tar.run_command(command, self.workspace)
        answer = {'status': 200, 'body': {'stdout': out, 'stderr': err, 'exit_code': rc}}
        if deliver:
            if (self.exchange / deliver['name']).exists():
                return dict(answer, delivered={'error': 'EXISTS'})
            out, delivered = tar.deliver(out, self.exchange, deliver['name'])
            answer['body']['stdout'] = out
            answer['delivered'] = delivered
        return answer

    def raw(self, method, path, body):
        self.calls.append(('raw', method, path))
        if method == 'POST':
            self.created = True
            return {'status': 201, 'body': {'id': FIXTURE['conversation_id']}}
        if path.endswith('/runtime'):
            return {'status': 200, 'body': {'runtime_status': 'available', 'can_resume': True}}
        return {'status': 200, 'body': {'success': True}}


@unittest.skipIf(tar.BASH is None, 'no Git Bash (Windows) or bash: the commands run in a real shell')
class Rehearsal(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-step0-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_every_step_of_the_rehearsal_passes_against_the_fake_guest(self):
        guest_ = FakeContainer(self.tmp)
        (self.tmp / 'host').mkdir()
        puller = tar.Puller(self.tmp / 'host', guest_.exchange)
        routes = (S0.REPO / 'profiles' / S0.PROFILE_ID / 'agent-server' / 'routes.json').read_bytes()
        (self.tmp / 'work').mkdir()
        out = S0.rehearse(transport=guest_.transport, raw=guest_.raw, pull=puller, routes_bytes=routes,
                          fixture_body=FIXTURE, workdir=self.tmp / 'work')
        self.assertEqual(out['result'], 'PASS', [s for s in out['steps'] if not s['ok']])
        steps = {s['step']: s for s in out['steps']}
        result = steps['RESULT, delivered (os.link, exclusive)']
        self.assertTrue(result['pathspec_exclusion'])
        self.assertTrue(result['index_info'])
        self.assertEqual(steps[f'a command of {S0.MAX_ARG_STRLEN + 8192} bytes']['status'], 500)
        self.assertTrue(steps[f'a command of {S0.MAX_ARG_STRLEN - 4096} bytes']['ran'])
        sizes = steps['the commands built (synthetic, demo-size)']['sizes']
        self.assertTrue(10000 < sizes['seed'] < 40000, sizes)
        self.assertTrue(30000 < sizes['result'] < S0.MAX_ARG_STRLEN, sizes)
        self.assertEqual(guest_.calls[-1], ('raw', 'DELETE', f'/api/conversations/{FIXTURE["conversation_id"]}'))
        self.assertEqual(puller.names, [AR.result_name(steps['the host intake: the commit-id equality and the tree '
                                                             'policy']['result']['attemptId'])])

    def rehearse(self, pull=None, where='a'):
        base = self.tmp / where
        base.mkdir()
        guest_ = FakeContainer(base)
        (base / 'host').mkdir()
        puller = tar.Puller(base / 'host', guest_.exchange)
        routes = (S0.REPO / 'profiles' / S0.PROFILE_ID / 'agent-server' / 'routes.json').read_bytes()
        (base / 'work').mkdir()
        out = S0.rehearse(transport=guest_.transport, raw=guest_.raw, pull=pull or puller, routes_bytes=routes,
                          fixture_body=FIXTURE, workdir=base / 'work')
        return out, guest_

    def test_a_refused_intake_or_pull_is_recorded_never_raised(self):
        """Review of B and C, S4 (the reviewer's probe_step0_raise): the refusal is in the record, the fixture
        conversation deleted, the result FAIL."""
        delete = ('raw', 'DELETE', f'/api/conversations/{FIXTURE["conversation_id"]}')
        with mock.patch.object(AR, 'intake_result', side_effect=di.DispatchRefused('RESULT_TREE_REFUSED', 'a path')):
            out, guest_ = self.rehearse()
        intake = [s for s in out['steps'] if s['step'].startswith('the host intake')]
        self.assertEqual((out['result'], intake[0]['ok'], intake[0]['refused']['code']),
                         ('FAIL', False, 'RESULT_TREE_REFUSED'))
        self.assertEqual(guest_.calls[-1], delete)
        out, guest_ = self.rehearse(pull=lambda name: {'result': 'refused', 'code': 'BUNDLE_REFUSED'}, where='b')
        pulled = [s for s in out['steps'] if s['step'].startswith('exchange pull')]
        self.assertEqual((out['result'], pulled[0]['ok'], pulled[0]['pull_result']), ('FAIL', False, 'refused'))
        self.assertFalse([s for s in out['steps'] if s['step'].startswith('the host intake')])
        self.assertEqual(guest_.calls[-1], delete)

    def test_the_rehearsal_touches_no_live_managed_root(self):
        """The reviewer's probe_step0_live_root: every integrations/paths resolution is a throwaway root with no
        configuration file, and no configuration file or integration store outside the temporary directories is
        opened."""
        resolved, opened, armed = [], [], [True]
        temp = Path(tempfile.gettempdir()).resolve()
        real = di.paths.resolve

        def resolve(*args, **kwargs):
            resolved.append((args, kwargs))
            return real(*args, **kwargs)

        def hook(event, args):
            if armed[0] and event == 'open' and args and isinstance(args[0], (str, bytes)):
                path = os.fsdecode(args[0]).replace('\\', '/').lower()
                if path.endswith(('/config.yml', '.sqlite', '.sqlite-wal')) and \
                        not path.startswith(temp.as_posix().lower()):
                    opened.append(path)
        sys.addaudithook(hook)
        try:
            with mock.patch.object(di.paths, 'resolve', resolve):
                out, _ = self.rehearse()
        finally:
            armed[0] = False
        self.assertEqual(out['result'], 'PASS')
        self.assertEqual(opened, [])
        for args, kwargs in resolved:
            self.assertEqual(kwargs.get('config'), {})
            root = Path((args[0] if args else kwargs.get('environ'))['AIEH_DATA_ROOT']).resolve()
            self.assertTrue(root.is_relative_to(temp), root)

    def test_the_test_only_builders_are_the_rehearsal_s(self):
        self.assertIn(S0.EDIT_BUILDER, di._TEST_BUILDER_NAMES)
        self.assertNotIn(S0.EDIT_BUILDER, di.COMMAND_BUILDER_NAMES)
        self.assertEqual(S0.build_edit('aieh-d1-demo').builder, S0.EDIT_BUILDER)


if __name__ == '__main__':
    unittest.main()
