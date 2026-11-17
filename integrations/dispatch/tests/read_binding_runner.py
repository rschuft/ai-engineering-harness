"""Run dispatch test modules with the fixture core's read record installed (E-01.4.2 slice 5c's read-binding test).

    <tools python> -I -B integrations/dispatch/tests/read_binding_runner.py [--served [--scenario NAME]] <out.json>
        <test module file name>...

With ``--served`` (E-01.7's extension), every request a test sends to a core (``AgentServerCore.__call__``) goes over
HTTP to the served fixture's listener (``integrations/agentfixture/server.py``, in a thread of this process, on a free
loopback port), through the fixture transport (``transport.py``), the listener answering from that same core (its
subclass's knobs included); the read record is then installed at the fixture transport's answer boundary, on the
answer as it arrived. A request no wire can carry (a keyword argument, the exchange delivery) is answered in process,
as before: the core refuses every one. ``--scenario`` chooses the listener's scenario (``finished`` by default; the
``failed`` scenario answers every key-gated request ``unauthorized``, S-01.3.1's refusal). The locked openapi.json the listener validates creates with is the one
``AIEH_LOCKED_OPENAPI`` names (sha256-checked); without it every create is refused, as the listener does.

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


def served(core, reads, scenario='finished'):
    """The served mode: the listener in a thread, and every core's ``__call__`` sent over HTTP to it (the module
    docstring). Returns the listener (stopped by the caller)."""
    support = HERE.parents[1] / 'agentfixture' / 'tests' / 'fixture_support.py'
    sys.path.insert(0, str(support.parent))
    spec = importlib.util.spec_from_file_location('fixture_support', support)
    S = importlib.util.module_from_spec(spec)
    sys.modules['fixture_support'] = S
    spec.loader.exec_module(S)
    document = S.locked_openapi_path()
    fixture = S.SERVER.Fixture(scenario, openapi=None if document is None else S.SERVER.locked_document(document))
    original = core.AgentServerCore.__call__
    fixture.call = lambda method, path, body: original(fixture.core, method, path, body)
    listener = S.InThread(fixture).start()
    transport = listener.transport(timeout=120)

    def over_the_wire(self, method, path, body=None, **kwargs):
        if kwargs or not isinstance(method, str) or not isinstance(path, str) or not path.startswith('/') \
                or path.startswith('/ui'):
            return original(self, method, path, body, **kwargs)
        fixture.core = self
        held, core.RECORDER = core.RECORDER, None          # the server side makes plain answers
        try:
            answer = transport(method, path, body)
        finally:
            core.RECORDER = held
        return core._wrap(answer, reads, answer['fixture']['answer'], '')
    core.AgentServerCore.__call__ = over_the_wire
    return listener


def main(argv):
    is_served = bool(argv) and argv[0] == '--served'
    argv = argv[1:] if is_served else argv
    scenario = 'finished'
    if is_served and argv[:1] == ['--scenario']:
        scenario, argv = argv[1], argv[2:]
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
    listener = served(core, reads, scenario) if is_served else None
    suite = unittest.TestSuite()
    for module in modules:
        suite.addTests(unittest.TestLoader().discover(str(HERE), pattern=module, top_level_dir=str(HERE)))
    try:
        result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
    finally:
        if listener is not None:
            listener.stop()
    out.write_text(json.dumps({
        'modules': modules, 'tests': result.testsRun, 'skipped': len(result.skipped),
        'failures': [test.id() for test, _ in result.failures + result.errors]
        + [test.id() for test in result.unexpectedSuccesses],
        'answers': answers, 'reads': reads.to_json(), 'readers': reads.readers_json(), 'served': is_served,
        'refused': [r for r in (listener.fixture.log if listener is not None else []) if r.get('answer') == 'refusal'],
        'failed': {test.id(): text[-600:] for test, text in result.failures + result.errors}}, indent=1),
        encoding='utf-8')
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
