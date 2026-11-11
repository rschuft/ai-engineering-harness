"""Run the test suites concurrently: ``task test`` (the Owner's direction of 2026-11-11, test
runtime is diagnostic, not a gate: prefer parallel tests wherever they are deterministic and
independent).

The suites are those of ``task test:serial`` in Taskfile.yml, read as ``tools/test_profile.py``
reads them. Each runs as ``<python> -I -B -m unittest discover -s <suite> -v`` (``<python>`` is
the interpreter running this script) in a child process of its own, from the repository root,
with an empty managed data root of its own (``AIEH_DATA_ROOT``, a new directory under a temporary
directory outside the checkout) and ``PYTHONDONTWRITEBYTECODE=1``. Suites share no process, no data
root and no output; the tests and their outcomes are those of the serial run. Each child is
started with the shared no-window helper's flags (integrations/platform/no_window.py), and each
suite stops the processes it starts, as in the serial run; if this runner is interrupted it kills
the suites still running and waits for them. A suite's output is printed whole when it ends,
then a summary in Taskfile order with each suite's result and wall time, and the whole run's wall
time, as information only.

Usage (from the repository root):
    python -I -B tools/run_tests.py [--jobs N] [--suite NAME ...]

``--jobs`` caps the suites running at once (default: every suite, at most the number of
processors). Exit status: 0 when every suite passed, 1 when one did not, 2 could not run.
"""
import argparse
import importlib.util
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_RAN = re.compile(r'^Ran (\d+) tests? in ', re.MULTILINE)
# unittest's verdict line; a test's own stdout, flushed when the suite's process exits, may follow it.
_VERDICT = re.compile(r'^(?:OK|FAILED)(?: \(.*\))?$', re.MULTILINE)


def _no_window():
    """integrations/platform/no_window.py, the shared no-window helper, loaded by path once per process:
    ``_no_window().no_window_flags()`` is CREATE_NO_WINDOW only where this process has no console."""
    module = sys.modules.get('aieh_no_window')
    if module is None:
        spec = importlib.util.spec_from_file_location(
            'aieh_no_window', REPO / 'integrations' / 'platform' / 'no_window.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        sys.modules['aieh_no_window'] = module
    return module


def _profiler():
    spec = importlib.util.spec_from_file_location('test_profile', REPO / 'tools' / 'test_profile.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def suite_argv(python, start_dir):
    return [python, '-I', '-B', '-m', 'unittest', 'discover', '-s', start_dir, '-v']


def summary_line(text):
    """'<N> tests, <verdict>' from a suite's output, e.g. '12 tests, OK (skipped=1)': unittest's last
    verdict line, else the last line of the output."""
    ran = _RAN.findall(text)
    verdicts = _VERDICT.findall(text.replace(chr(13), ''))
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    last = verdicts[-1] if verdicts else lines[-1] if lines else 'no output'
    return f'{ran[-1] if ran else "?"} tests, {last}'


def _stop(started):
    """Kill every started suite that still runs, and wait for each."""
    for process in started:
        if process.poll() is None:
            process.kill()
    for process in started:
        process.wait()


def run(suites, jobs, repo=REPO, python=sys.executable, out=sys.stdout, temp_parent=None,
        popen=subprocess.Popen):
    """Run SUITES ([(name, start_dir)]) at most JOBS at a time; print each suite's output as it
    ends and then the summary. Returns 0 when every suite exited 0, else 1."""
    t0 = time.perf_counter()
    results = {}
    done = queue.Queue()
    started = []
    with tempfile.TemporaryDirectory(prefix='aieh-test-run-', dir=temp_parent,
                                     ignore_cleanup_errors=True) as tmp:
        def wait(name, process, began):
            process.wait()
            done.put((name, process.returncode, time.perf_counter() - began))

        pending = list(suites)
        logs = {}
        try:
            running = 0
            while pending or running:
                while pending and running < jobs:
                    name, start_dir = pending.pop(0)
                    data_root = Path(tmp) / name / 'data'
                    data_root.mkdir(parents=True)
                    env = dict(os.environ, AIEH_DATA_ROOT=str(data_root), PYTHONDONTWRITEBYTECODE='1')
                    logs[name] = Path(tmp) / name / 'output.log'
                    with open(logs[name], 'wb') as log:
                        process = popen(suite_argv(python, start_dir), cwd=str(repo), env=env,
                                        stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                        creationflags=_no_window().no_window_flags())
                    started.append(process)
                    running += 1
                    threading.Thread(target=wait, args=(name, process, time.perf_counter()),
                                     daemon=True).start()
                name, code, wall = done.get()
                running -= 1
                text = logs[name].read_text(encoding='utf-8', errors='replace')
                results[name] = (code, wall, summary_line(text))
                out.write(f'===== {name} (exit {code}, {wall:.1f} s) =====\n{text}')
                if not text.endswith('\n'):
                    out.write('\n')
                out.flush()
        except BaseException:
            _stop(started)
            raise
    total = time.perf_counter() - t0
    out.write('===== summary =====\n')
    for name, _ in suites:
        code, wall, line = results[name]
        out.write(f'{"ok  " if code == 0 else "FAIL"} {name:<12} {wall:7.1f} s  {line}\n')
    failed = [name for name, _ in suites if results[name][0] != 0]
    out.write(f'{len(suites)} suites, {len(failed)} failed, {jobs} at a time; wall {total:.1f} s '
              f'(information, not a gate)\n')
    out.flush()
    return 1 if failed else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--jobs', type=int, default=0,
                        help='suites at once (default: every suite, at most the processors)')
    parser.add_argument('--suite', action='append', default=[], help='run only this suite')
    args = parser.parse_args(argv)
    profiler = _profiler()
    try:
        suites = profiler.select_suites(args.suite)
    except profiler.ProfileError as exc:
        print(f'could not run: {exc}', file=sys.stderr)
        return 2
    if args.jobs < 0:
        print('could not run: --jobs must be positive', file=sys.stderr)
        return 2
    jobs = args.jobs or max(1, min(len(suites), os.cpu_count() or 1))
    return run(suites, jobs)


if __name__ == '__main__':
    sys.exit(main())
