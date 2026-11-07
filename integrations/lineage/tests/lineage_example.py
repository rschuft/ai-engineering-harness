"""The P-03.2 lineage projection example: build it, trace it, and record it.

``build`` creates, in a throwaway directory:

- the P-02.1 project repository (``two_task_fixture.build_repo``: the qual-02 change, its
  reproducible design commit), then a second commit that declares the outcome of O1 under
  ``x-outcomes`` in the change's ``.openspec.yaml`` (decision 0008), as the acceptance
  recorder would; the qual-02 fixture itself is never edited;
- Backlog.md's own recorded ``task list --json`` and ``task view --json`` output for the
  two tasks P-02.1 created (``integrations/planning/tests/fixtures/two-task/recorded/``),
  replayed by the fake Backlog.md, so the tasks carry the real design pointers;
- an integration store (F-05.1) with one attempt reservation per task, made through the
  store's own API, whose intent cites the task (``workRef``) and the outcome
  (``outcomeRef``).

``example`` traces the outcome, pinned at the declaring commit, twice: with the sample
authorities (``lineage_samples.py``: the whole chain resolves, and is marked sample) and
with the real registry only (statements and attempts are ``authority-unavailable``).

Record or refresh the committed example (offline):

    python -I -B integrations/lineage/tests/lineage_example.py --record
"""
import argparse
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
LINEAGE_DIR = HERE.parent
REPO = LINEAGE_DIR.parents[1]
PLANNING_TESTS = REPO / 'integrations' / 'planning' / 'tests'


def _load(name, path):
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


T = _load('lineage_trace', LINEAGE_DIR / 'lineage_trace.py')
S = _load('lineage_samples', LINEAGE_DIR / 'lineage_samples.py')
R = T.resolve_mod
L = T.L
sys.path.insert(0, str(PLANNING_TESTS))
import two_task_fixture as fx  # noqa: E402

FAKE_BACKLOG = [sys.executable, '-I', '-B', str(PLANNING_TESTS / 'fake_backlog.py')]
RECORDED_TASKS = PLANNING_TESTS / 'fixtures' / 'two-task' / 'recorded'
EXAMPLES = LINEAGE_DIR / 'examples'
FILES = {'sample': 'projection-sample-authorities.json', 'real': 'projection-real-registry.json'}
CHANGE = fx.CHANGE
CHANGE_DIR = f'openspec/changes/{CHANGE}'
OUTCOME = '5c6f4c1e-8d3a-4a3b-9b2e-1f0e7d6c5b4a'
ACCEPTANCE = 'conversation:qual-02/message-2'
DECLARED_DATE = '2026-11-07T00:01:00Z'


def operation_key(task):
    """The example's durable attempt key (the blueprint's illustrative form)."""
    return f'work-{task}/implement/revision-1'


def declaration(outcome=OUTCOME, item='O1', acceptance=ACCEPTANCE):
    return f'x-outcomes:\n  {outcome}:\n    item: {item}\n    acceptance: {acceptance}\n'.encode('utf-8')


def declare(repo, change_dir=CHANGE_DIR, data=None):
    """Append an x-outcomes declaration to a change's .openspec.yaml in a throwaway repository."""
    meta = Path(repo) / change_dir / '.openspec.yaml'
    meta.write_bytes(meta.read_bytes() + (declaration() if data is None else data))


def edit(repo, path, old, new):
    target = Path(repo) / path
    data = target.read_bytes()
    if data.count(old) != 1:
        raise AssertionError(f'{path}: expected one {old!r}')
    target.write_bytes(data.replace(old, new, 1))


def build_project(repo):
    """(design commit, declaring commit) of the example project repository."""
    design = fx.build_repo(repo)
    declare(repo)
    declared = fx.commit_all(repo, 'accept O1 of qual-02: declare its outcome id', date=DECLARED_DATE)
    return design, declared


def store_module():
    return T._store_module()


def build_store(path, intents):
    """An integration store at PATH with one reservation per (operation key, intent)."""
    store_mod = store_module()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with store_mod.open_store(path) as store:
        return [store.reserve(key, intent, actor='p-03.2-example').reservation for key, intent in intents]


def task_intent(task, outcome=OUTCOME):
    intent = {'workRef': f'backlog:{task}'}
    if outcome is not None:
        intent['outcomeRef'] = f'outcome:{outcome}'
    return intent


def registry(repo, backlog=FAKE_BACKLOG):
    return R.build_registry(project=repo, backlog=backlog)


def authorities(repo, samples=True, backlog=FAKE_BACKLOG):
    return T.Authorities(registry(repo, backlog), S.sample_authorities() if samples else None)


def run_trace(outcome, auth, repo, store, backlog=FAKE_BACKLOG, snapshot=RECORDED_TASKS):
    """The projection, with the fake Backlog.md replaying SNAPSHOT (None: its own state)."""
    env = {'FAKE_BACKLOG_SNAPSHOT': str(snapshot)} if snapshot is not None else {}
    with mock.patch.dict(os.environ, env):
        if snapshot is None:
            os.environ.pop('FAKE_BACKLOG_SNAPSHOT', None)
        return T.trace(outcome, auth, project=repo, backlog=backlog, store=store)


def build(work):
    """Build the example's sources under WORK; return (repo, store, declared commit)."""
    work = Path(work)
    repo = work / 'p'
    _design, declared = build_project(repo)
    store = work / 'st' / 'integration.sqlite'
    build_store(store, [(operation_key(t), task_intent(t)) for t in ('TASK-1', 'TASK-2')])
    return repo, store, declared


def example(work):
    """{'sample': projection, 'real': projection} of the example built under WORK."""
    repo, store, declared = build(work)
    outcome = f'outcome:{OUTCOME}@{declared}'
    return {'sample': run_trace(outcome, authorities(repo, True), repo, store),
            'real': run_trace(outcome, authorities(repo, False), repo, store)}


def dumps(data):
    return json.dumps(data, indent=2, ensure_ascii=False) + '\n'


def recorded():
    return {name: json.loads((EXAMPLES / FILES[name]).read_text(encoding='utf-8')) for name in FILES}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Build and trace the P-03.2 lineage example.')
    parser.add_argument('--record', action='store_true', help='write the projections into examples/')
    args = parser.parse_args(argv)
    work = Path(tempfile.mkdtemp(prefix='aieh-lineage-example-'))
    try:
        projections = example(work)
        for name, projection in projections.items():
            text = dumps(projection)
            if fx.MACHINE_PATH.search(text):
                print(f'ERROR {FILES[name]} names a machine path', file=sys.stderr)
                return 1
            if args.record:
                EXAMPLES.mkdir(exist_ok=True)
                (EXAMPLES / FILES[name]).write_text(text, encoding='utf-8', newline='\n')
            print(f'{FILES[name]}: verdict {projection["verdict"]}, {len(projection["nodes"])} nodes, '
                  f'{len(projection["edges"])} edges, {len(projection["uncertainties"])} uncertainties'
                  + (' (recorded)' if args.record else ''))
        return 0
    finally:
        fx.rmtree(work)


if __name__ == '__main__':
    sys.exit(main())
