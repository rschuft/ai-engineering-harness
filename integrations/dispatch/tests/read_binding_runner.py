"""Run dispatch test modules with the fixture core's read record installed (E-01.4.2 slice 5c's read-binding test).

    <tools python> -I -B integrations/dispatch/tests/read_binding_runner.py <out.json> <test module file name>...

Before any test module is loaded, the fixture catalog's core is loaded under the name the test modules share
(``agentfixture_core``) and a ``Reads`` recorder installed, so that every answer the core makes in this process records
each key read of it, by catalog answer and field path; the core also counts its answers here. The named modules are
then run with unittest, and OUT receives their results, the answers made, the reads (each opaque read included) and
the readers of each read (``readers``). Not a test module itself.
"""
from pathlib import Path
import importlib.util
import io
import json
import sys
import unittest

HERE = Path(__file__).resolve().parent
CORE = HERE.parents[1] / 'agentfixture' / 'core.py'


def main(argv):
    out, modules = Path(argv[0]), argv[1:]
    spec = importlib.util.spec_from_file_location('agentfixture_core', CORE)
    core = importlib.util.module_from_spec(spec)
    sys.modules['agentfixture_core'] = core
    spec.loader.exec_module(core)
    reads, answers = core.Reads(), {}
    made = core.AgentServerCore.made

    def counting(self, answer, *args, **kwargs):
        answers[answer] = answers.get(answer, 0) + 1
        return made(self, answer, *args, **kwargs)
    core.AgentServerCore.made = counting
    core.RECORDER = reads
    suite = unittest.TestSuite()
    for module in modules:
        suite.addTests(unittest.TestLoader().discover(str(HERE), pattern=module, top_level_dir=str(HERE)))
    result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
    out.write_text(json.dumps({
        'modules': modules, 'tests': result.testsRun, 'skipped': len(result.skipped),
        'failures': [test.id() for test, _ in result.failures + result.errors]
        + [test.id() for test in result.unexpectedSuccesses],
        'answers': answers, 'reads': reads.to_json(), 'readers': reads.readers_json()}, indent=1), encoding='utf-8')
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
