"""Tests for tools/run_tests.py, the concurrent runner of ``task test`` (the Owner's direction of
2026-11-11: parallel by default where deterministic and independent).

Run from the repository root:  python -I -B -m unittest discover -s tools/tests -v

The unit cases drive the runner with a stand-in for ``subprocess.Popen``: each suite's command,
its own empty data root, the no-window flags, the cap on suites at once, the exit status, the
output and the stop on an interruption. The integration case runs two small real suites, one
passing and one failing, in a temporary directory outside the checkout.
"""
from pathlib import Path
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import textwrap
import threading
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location('run_tests', REPO / 'tools' / 'run_tests.py')
rt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rt)

CATEGORY = 'unit'
SUITES = [('tools', 'tools/tests'), ('store', 'integrations/store/tests'),
          ('effects', 'integrations/effects/tests')]


class FakeProcess:
    """A stand-in for subprocess.Popen: records its arguments, writes OUTPUT to the stdout it is
    given and ends with CODE when waited for (after BARRIER, when one is given)."""

    def __init__(self, owner, argv, **kwargs):
        self.argv, self.kwargs = argv, kwargs
        self.returncode = None
        self.killed = False
        self.stopped = threading.Event()
        self.passed = False
        self.start_dir = argv[argv.index('-s') + 1]
        data_root = Path(kwargs['env']['AIEH_DATA_ROOT'])
        owner.data_roots[self.start_dir] = (data_root, data_root.is_dir() and not any(data_root.iterdir()))
        kwargs['stdout'].write(owner.outputs.get(self.start_dir, b'Ran 2 tests in 0.1s\n\nOK\n'))
        self.code = owner.codes.get(self.start_dir, 0)
        self.owner = owner
        with owner.lock:
            owner.running += 1
            owner.most = max(owner.most, owner.running)

    def poll(self):
        return self.returncode

    def wait(self):
        if self.owner.hold:
            self.stopped.wait(30)  # a ceiling against a hang; kill() ends it
        elif self.owner.barrier is not None and not self.passed:
            self.passed = True
            self.owner.barrier.wait()
        with self.owner.lock:
            if self.returncode is None:
                self.owner.running -= 1
                self.returncode = -9 if self.killed else self.code
        return self.returncode

    def kill(self):
        self.killed = True
        self.stopped.set()


class Launcher:
    def __init__(self, codes=None, outputs=None, barrier=None, refuse=None, hold=False):
        self.codes, self.outputs, self.barrier, self.refuse = codes or {}, outputs or {}, barrier, refuse
        self.hold = hold
        self.processes, self.data_roots = [], {}
        self.running = self.most = 0
        self.lock = threading.Lock()

    def __call__(self, argv, **kwargs):
        if self.refuse is not None and argv[argv.index('-s') + 1] == self.refuse:
            raise KeyboardInterrupt
        process = FakeProcess(self, argv, **kwargs)
        self.processes.append(process)
        return process


class RunnerTests(unittest.TestCase):
    def run_suites(self, launcher, jobs=3, suites=SUITES):
        out = io.StringIO()
        status = rt.run(suites, jobs, repo=REPO, python='PY', out=out, popen=launcher)
        return status, out.getvalue()

    def test_each_suite_runs_its_unittest_discovery_with_an_empty_data_root_of_its_own(self):
        launcher = Launcher()
        status, _ = self.run_suites(launcher)
        self.assertEqual(status, 0)
        self.assertEqual([p.argv for p in launcher.processes],
                         [['PY', '-I', '-B', '-m', 'unittest', 'discover', '-s', start, '-v'] for _, start in SUITES])
        roots = [launcher.data_roots[start][0] for _, start in SUITES]
        self.assertEqual(len(set(roots)), len(SUITES))
        self.assertTrue(all(empty for _, empty in launcher.data_roots.values()))
        for (name, _), root in zip(SUITES, roots):
            self.assertEqual(root.parent.name, name)
            self.assertFalse(root.exists(), 'the data roots are removed after the run')
            self.assertNotIn(str(REPO), str(root))
        for process in launcher.processes:
            self.assertEqual(process.kwargs['cwd'], str(REPO))
            self.assertEqual(process.kwargs['env']['PYTHONDONTWRITEBYTECODE'], '1')
            self.assertEqual(process.kwargs['creationflags'], rt._no_window().no_window_flags())
            self.assertIs(process.kwargs['stdin'], subprocess.DEVNULL)
            self.assertIs(process.kwargs['stderr'], subprocess.STDOUT)

    def test_the_suites_run_concurrently_and_at_most_jobs_at_once(self):
        launcher = Launcher(barrier=threading.Barrier(3, timeout=30))
        self.assertEqual(self.run_suites(launcher, jobs=3)[0], 0)  # the barrier needs all three at once
        self.assertEqual(launcher.most, 3)
        suites = SUITES + [('paths', 'integrations/paths/tests')]
        launcher = Launcher(barrier=threading.Barrier(2, timeout=30))
        self.assertEqual(self.run_suites(launcher, jobs=2, suites=suites)[0], 0)
        self.assertEqual(launcher.most, 2)

    def test_one_failing_suite_fails_the_run_and_every_output_is_printed(self):
        launcher = Launcher(codes={'integrations/store/tests': 1},
                            outputs={'integrations/store/tests': b'test_x (m.C.test_x) ... FAIL\n'
                                                                b'Ran 3 tests in 0.2s\n\nFAILED (failures=1)\n'})
        status, out = self.run_suites(launcher)
        self.assertEqual(status, 1)
        self.assertIn('===== store (exit 1, ', out)
        self.assertIn('test_x (m.C.test_x) ... FAIL', out)
        summary = out.split('===== summary =====\n')[1].splitlines()
        self.assertEqual([line.split()[:2] for line in summary[:3]],
                         [['ok', 'tools'], ['FAIL', 'store'], ['ok', 'effects']])
        self.assertIn('3 tests, FAILED (failures=1)', summary[1])
        self.assertTrue(summary[3].startswith('3 suites, 1 failed, 3 at a time; wall '))
        self.assertTrue(summary[3].endswith('s (information, not a gate)'))

    def test_an_interruption_stops_the_suites_already_started(self):
        launcher = Launcher(refuse='integrations/effects/tests', hold=True)
        with self.assertRaises(KeyboardInterrupt):
            self.run_suites(launcher)
        self.assertEqual(len(launcher.processes), 2)
        self.assertTrue(all(p.killed and p.returncode == -9 for p in launcher.processes))

    def test_the_summary_line_of_a_suite(self):
        self.assertEqual(rt.summary_line('a\nRan 12 tests in 1.0s\n\nOK (skipped=1)\n'), '12 tests, OK (skipped=1)')
        self.assertEqual(rt.summary_line('Ran 1 test in 0.0s\nOK\n'), '1 tests, OK')
        self.assertEqual(rt.summary_line(''), '? tests, no output')
        # A test's own stdout, flushed when the suite's process exits, follows unittest's verdict.
        self.assertEqual(rt.summary_line('Ran 3 tests in 1.0s\r\n\r\nOK (skipped=1)\r\n{\n  "a": 1\n}\n'),
                         '3 tests, OK (skipped=1)')
        self.assertEqual(rt.summary_line('Ran 3 tests in 1.0s\n\nFAILED (errors=2)\nprinted\n'),
                         '3 tests, FAILED (errors=2)')
        self.assertEqual(rt.summary_line('Traceback (most recent call last):\nSystemExit: 2\n'),
                         '? tests, SystemExit: 2')

    def test_unknown_suites_and_bad_jobs_cannot_run(self):
        with mock.patch('sys.stderr', io.StringIO()) as err, mock.patch('sys.stdout', io.StringIO()):
            self.assertEqual(rt.main(['--suite', 'no-such-suite']), 2)
            self.assertEqual(rt.main(['--jobs', '-1']), 2)
        self.assertIn('unknown suite(s): no-such-suite', err.getvalue())

    def test_the_output_is_encoding_safe(self):
        # A redirected standard output under -I has the locale's encoding (cp1252 on Windows): the runner writes
        # UTF-8 instead, with a backslash escape for what UTF-8 cannot encode, never UnicodeEncodeError.
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding='cp1252', newline='\n')
        self.assertIs(rt.encoding_safe(stream), stream)
        stream.write('\ufffd \u0661 \ud800\n')
        stream.flush()
        self.assertEqual(raw.getvalue(), '\ufffd \u0661 '.encode('utf-8') + b'\\ud800\n')
        plain = io.StringIO()
        self.assertIs(rt.encoding_safe(plain), plain)  # no reconfigure: as it is

    def test_main_writes_through_the_encoding_safe_stream(self):
        raw, err = io.BytesIO(), io.BytesIO()
        stdout = io.TextIOWrapper(raw, encoding='cp1252')
        stderr = io.TextIOWrapper(err, encoding='cp1252')
        seen = {}

        def run(suites, jobs, out):
            seen['out'] = out
            out.write('===== tools (exit 0, 0.1 s) =====\ncaf\ufffd\n')
            out.flush()
            return 0

        with mock.patch('sys.stdout', stdout), mock.patch('sys.stderr', stderr), mock.patch.object(rt, 'run', run):
            self.assertEqual(rt.main(['--suite', 'tools']), 0)
        self.assertIs(seen['out'], stdout)
        self.assertEqual((stdout.encoding, stderr.encoding), ('utf-8', 'utf-8'))
        self.assertIn('caf\ufffd'.encode('utf-8'), raw.getvalue())


class RealSuitesTests(unittest.TestCase):
    """Two small suites run as real child processes of this interpreter."""
    category = 'integration'

    def test_two_real_suites_one_failing(self):
        check = textwrap.dedent('''\
            import os, unittest
            from pathlib import Path

            class C(unittest.TestCase):
                def test_data_root(self):
                    root = Path(os.environ['AIEH_DATA_ROOT'])
                    self.assertTrue(root.is_dir())
                    self.assertEqual(list(root.iterdir()), [])
                    (root / 'mine').write_text('x')
                    self.assertEqual(os.environ['PYTHONDONTWRITEBYTECODE'], '1')

                def test_outcome(self):
                    self.assertEqual(os.environ.get('OUTCOME'), 'pass')
            ''')
        with tempfile.TemporaryDirectory(prefix='aieh-run-tests-') as tmp:
            root = Path(tmp)
            for name in ('a', 'b'):
                (root / name / 'tests').mkdir(parents=True)
                (root / name / 'tests' / f'test_{name}.py').write_text(
                    check.replace("os.environ.get('OUTCOME')", "'pass'" if name == 'a' else "'fail'"),
                    encoding='utf-8')
            (root / 'scratch').mkdir()
            out = io.StringIO()
            status = rt.run([('a', 'a/tests'), ('b', 'b/tests')], 2, repo=root, python=sys.executable,
                            out=out, temp_parent=root / 'scratch')
            text = out.getvalue()
            self.assertEqual(status, 1, text)
            self.assertIn('===== a (exit 0, ', text)
            self.assertIn('===== b (exit 1, ', text)
            self.assertRegex(text, r'ok   a +\d+\.\d s  2 tests, OK')
            self.assertRegex(text, r'FAIL b +\d+\.\d s  2 tests, FAILED \(failures=1\)')
            self.assertEqual(list((root / 'scratch').iterdir()), [], 'the data roots and logs are removed')
            self.assertEqual(sorted(p.name for p in root.rglob('__pycache__')), [])

    def test_a_redirected_run_survives_output_its_encoding_cannot_hold(self):
        # The runner's main, in a child process under -I with its standard output redirected to a file: a suite
        # writes bytes that are not UTF-8, read back as U+FFFD, which cp1252 (Windows' redirected default) cannot
        # encode. The run ends with its summary and exit 0, its output UTF-8.
        suite = textwrap.dedent('''\
            import sys, unittest

            class C(unittest.TestCase):
                def test_bytes(self):
                    sys.stdout.flush()
                    sys.stdout.buffer.write(b'caf\\xe9 \\xd9\\xa1\\n')
                    sys.stdout.buffer.flush()
            ''')
        child = textwrap.dedent('''\
            import functools, importlib.util, sys
            from pathlib import Path
            repo, root = Path(sys.argv[1]), Path(sys.argv[2])
            spec = importlib.util.spec_from_file_location('run_tests', repo / 'tools' / 'run_tests.py')
            rt = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(rt)

            class Profiler:
                class ProfileError(Exception):
                    pass

                @staticmethod
                def select_suites(names):
                    return [('a', 'a/tests')]

            rt._profiler = lambda: Profiler
            rt.run = functools.partial(rt.run, repo=root, temp_parent=root / 'scratch')
            sys.exit(rt.main(['--suite', 'a', '--jobs', '1']))
            ''')
        with tempfile.TemporaryDirectory(prefix='aieh-run-tests-') as tmp:
            root = Path(tmp)
            (root / 'a' / 'tests').mkdir(parents=True)
            (root / 'a' / 'tests' / 'test_a.py').write_text(suite, encoding='utf-8')
            (root / 'scratch').mkdir()
            (root / 'child.py').write_text(child, encoding='utf-8')
            env = {k: v for k, v in os.environ.items() if k not in ('PYTHONIOENCODING', 'PYTHONUTF8')}
            with open(root / 'out.log', 'wb') as log:
                status = subprocess.run([sys.executable, '-I', '-B', str(root / 'child.py'), str(REPO), str(root)],
                                        stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, env=env,
                                        timeout=120, creationflags=rt._no_window().no_window_flags()).returncode
            text = (root / 'out.log').read_bytes().decode('utf-8')
            self.assertEqual(status, 0, text)
            self.assertIn('caf�', text)
            self.assertRegex(text, r'ok   a +\d+\.\d s  1 tests?, OK')


if __name__ == '__main__':
    unittest.main()
