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
  (``outcomeRef``);
- an Owner conversation store (U-02.2), made through the store's own API and holding no
  thread: the qual-02 change cites the P-01.2 corpus's statements
  (``conversation:qual-02/...``), which are not Owner conversation store identities.

``build_conversations`` makes an Owner conversation store that holds the three corpus
statements the tests quote, under store identities (``STATEMENTS``), and ``cite_store``
points a throwaway project's intent record at them.

``example`` builds those sources, then fills the Owner conversation store with the statements
(``build_conversations``) and, in a third commit after the declaring one, points the intent
record at them (``cite_store``; never before the design commit, whose pointers the recorded
Backlog.md output carries). It dispatches the two tasks' attempts in an integration store of
their own (``build_dispatched``: the dispatcher's records, made through the store's own API by
``fixture_attempts``, each create answered by the Agent Server fixture's cited core, bound to a
route allowlist that declares the fixture authority). It traces the outcome, pinned at that
third commit, twice with the real registry, whose statement resolver reads that store: the
statements resolve authoritatively and Q1's quote is verified against the store's bytes, and the
recorded tasks' proposal pointer (pinned at the design commit) is superseded. Once with the
attempt resolver over the core (``fixture``: the attempts resolve, their mode stated ``fixture``,
each with the fixture-authority uncertainty) and once without it (``real``: no Agent Server is
configured, so the attempts are ``authority-unavailable``). Until U-02.2 a statement sample, and
until E-01.5 an attempt sample, stood in; both are retired (I1 work design, R5 and R11).
``build`` itself, which the tests share, is unchanged.

Record or refresh the committed example (offline):

    python -I -B integrations/lineage/tests/lineage_example.py --record
"""
import argparse
import hashlib
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
RA = _load('lineage_attempt', LINEAGE_DIR / 'lineage_attempt.py')
L = T.L
sys.path.insert(0, str(PLANNING_TESTS))
import two_task_fixture as fx  # noqa: E402
import fake_backlog  # noqa: E402

FAKE_BACKLOG = [sys.executable, '-I', '-B', str(PLANNING_TESTS / 'fake_backlog.py')]
RECORDED_TASKS = PLANNING_TESTS / 'fixtures' / 'two-task' / 'recorded'
CORPUS = REPO / 'tools' / 'tests' / 'fixtures' / 'intent_qualification' / 'corpus'
EXAMPLES = LINEAGE_DIR / 'examples'
FILES = {'fixture': 'projection-fixture-authority.json', 'real': 'projection-real-registry.json'}
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


DECLARE_MESSAGE = 'accept O1 of qual-02: declare its outcome id'


def _build_project(repo):
    design = fx.build_repo(repo)
    declare(repo)
    declared = fx.commit_all(repo, DECLARE_MESSAGE, date=DECLARED_DATE)
    return design, declared


def build_project(repo):
    """(design commit, declaring commit) of the example project repository: built once per
    process per input digest and copied (``two_task_fixture.golden``)."""
    key = fx.input_digest('build_project/1', fx.design_files(), fx.DESIGN_MESSAGE, fx.GIT_ENV,
                          declaration(), DECLARE_MESSAGE, DECLARED_DATE)
    return fx.golden(repo, key, _build_project)


def store_module():
    return T._store_module()


def in_process_backlog():
    """A patch of the Backlog runner seam (``planning_adapter.Backlog.runner``) that answers the
    fake Backlog.md in the test process: every Backlog.md read of the traversal and the
    resolvers, ``ReadOnlyBacklog`` included, then launches no process. Tests of the real
    process interaction leave it off."""
    return mock.patch.object(R.planning.Backlog, 'runner', fake_backlog.InProcessRunner(FAKE_BACKLOG))


def build_store(path, intents):
    """An integration store at PATH with one reservation per (operation key, intent).

    A new store in a new directory starts as a copy of one migrated, empty store made once per
    process (``two_task_fixture.golden``; plan leaf F-09): the store a fresh ``open_store``
    makes, its schema and rows the same (only the migrations' applied_at times differ), and
    ``open_store`` still verifies every applied migration against the migration files."""
    store_mod = store_module()
    path = Path(path)
    if not path.parent.exists():
        migrations = sorted(Path(store_mod.MIGRATIONS_DIR).glob('*.sql'))
        key = fx.input_digest('empty-integration-store/1', path.name, {m.name: m.read_bytes() for m in migrations})

        def empty_store(directory):
            directory.mkdir(parents=True)
            store_mod.open_store(directory / path.name).close()
        fx.golden(path.parent, key, empty_store)
    path.parent.mkdir(parents=True, exist_ok=True)
    with store_mod.open_store(path) as store:
        return [store.reserve(key, intent, actor='p-03.2-example').reservation for key, intent in intents]


def task_intent(task, outcome=OUTCOME):
    intent = {'workRef': f'backlog:{task}'}
    if outcome is not None:
        intent['outcomeRef'] = f'outcome:{outcome}'
    return intent


def registry(repo, backlog=FAKE_BACKLOG, conversations=None):
    """The real registry over REPO, Backlog.md and the Owner conversation store (by default the one beside
    REPO, ``conversations_path``)."""
    return R.build_registry(project=repo, backlog=backlog,
                            conversations=conversations_path(repo) if conversations is None else conversations)


def authorities(repo, samples=True, backlog=FAKE_BACKLOG, conversations=None):
    return T.Authorities(registry(repo, backlog, conversations), S.sample_authorities() if samples else None)


def run_trace(outcome, auth, repo, store, backlog=FAKE_BACKLOG, snapshot=RECORDED_TASKS):
    """The projection, with the fake Backlog.md replaying SNAPSHOT (None: its own state)."""
    env = {'FAKE_BACKLOG_SNAPSHOT': str(snapshot)} if snapshot is not None else {}
    with mock.patch.dict(os.environ, env):
        if snapshot is None:
            os.environ.pop('FAKE_BACKLOG_SNAPSHOT', None)
        return T.trace(outcome, auth, project=repo, backlog=backlog, store=store)


# ---------------------------------------------------------------------------
# The Owner conversation store (plan leaf U-02.2)

def conversation_module():
    return R._conversation_module()


def conversations_path(repo):
    """Where the example and the tests keep the Owner conversation store of the project REPO."""
    return Path(repo).parent / 'cv' / 'conversation.sqlite'


# Store identities for the P-01.2 corpus statements the tests quote: thread ids are the store's (UUID version 4,
# minted here by the store's own mint seam) and message ids assistant-ui's grammar (seven of [0-9A-Za-z]).
SESSION = '6a1d2c3b-4e5f-4a6b-8c7d-9e0f1a2b3c4d'
THREADS = {'qual-02': '0f6b2a7c-3d4e-4f5a-9b8c-7d6e5f4a3b2c', 'qual-08': '1e2d3c4b-5a69-4788-a7b6-c5d4e3f2a1b0'}
STATEMENTS = {'conversation:qual-02/message-1': ('qual-02', 'Q02msg1'),
              'conversation:qual-02/message-2': ('qual-02', 'Q02msg2'),
              'conversation:qual-08/message-1': ('qual-08', 'Q08msg1')}
STORE_AT = '2026-11-07T00:00:00Z'


def store_reference(corpus_reference):
    """The Owner conversation store reference of a corpus statement (``conversation:<thread>/<message>``)."""
    corpus_thread, message = STATEMENTS[corpus_reference]
    return f'conversation:{THREADS[corpus_thread]}/{message}'


def corpus_bytes(corpus_reference):
    """The corpus message's bytes (LF on every host): what the store keeps as the statement's content."""
    thread, message = L.parse(corpus_reference).thread, L.parse(corpus_reference).message
    return (CORPUS / thread / f'{message}.txt').read_bytes()


def build_conversations(path, statements=True):
    """An Owner conversation store at PATH, made by the store's own API. With STATEMENTS it holds the corpus
    statements of ``STATEMENTS`` as Owner statements (user messages, each the corpus file's text exactly), one
    thread per corpus thread, under one session; else it holds nothing."""
    cs = conversation_module()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with cs.open_store(path) as store:
        if not statements:
            return path
        store.enroll_session(session_id=SESSION, verifier=hashlib.sha256(b'lineage example session').hexdigest(),
                             issued_at=STORE_AT, expires_at='2026-11-08T00:00:00Z')
        last = {}
        for corpus_reference, (corpus_thread, message) in STATEMENTS.items():
            thread = THREADS[corpus_thread]
            store.initialize_thread(session_id=SESSION, local_id='__LOCALID_' + corpus_thread.replace('-', ''),
                                    at=STORE_AT, mint=lambda thread=thread: thread)
            text = corpus_bytes(corpus_reference).decode('utf-8')
            store.append_message(thread, {'parentId': last.get(thread), 'message': {
                'id': message, 'role': 'user', 'createdAt': '2026-11-07T00:00:00.000Z',
                'content': [{'type': 'text', 'text': text}], 'attachments': [], 'metadata': {'custom': {}}}},
                session_id=SESSION, at=STORE_AT)
            last[thread] = message
    return path


def cite_store(repo, change_dir=CHANGE_DIR):
    """Point the throwaway project's intent record (proposal.md and the x-outcomes declaration) at the store
    identities of the corpus statements it cites."""
    for name in ('proposal.md', '.openspec.yaml'):
        target = Path(repo) / change_dir / name
        data = target.read_bytes()
        for corpus_reference in STATEMENTS:
            data = data.replace(corpus_reference.encode(), store_reference(corpus_reference).encode())
        target.write_bytes(data)


def build(work):
    """Build the example's sources under WORK; return (repo, store, declared commit)."""
    work = Path(work)
    repo = work / 'p'
    _design, declared = build_project(repo)
    store = work / 'st' / 'integration.sqlite'
    build_store(store, [(operation_key(t), task_intent(t)) for t in ('TASK-1', 'TASK-2')])
    build_conversations(conversations_path(repo), statements=False)
    return repo, store, declared


CITE_MESSAGE = 'the intent record cites the Owner conversation store'
CITED_DATE = '2026-11-07T00:02:00Z'


def build_example(work):
    """The example's sources under WORK: ``build``, then the Owner conversation store's statements
    (``build_conversations``) and, in its own commit after the declaring one, the intent record pointed at them
    (``cite_store``). The recorded Backlog.md tasks keep their design pointers, pinned at the design commit.
    Return (repo, store, declared commit, cited commit)."""
    repo, store, declared = build(work)
    build_conversations(conversations_path(repo))
    cite_store(repo)
    return repo, store, declared, fx.commit_all(repo, CITE_MESSAGE, date=CITED_DATE)


def build_dispatched(work, repo, declared):
    """The two tasks' attempts, dispatched (``fixture_attempts.FixtureAttempts``) in an integration store of their own
    under WORK, each create answered by a fresh Agent Server fixture core; the design revision is the change at the
    design commit (the declaring commit's parent). Return (the store's path, the attempt resolver over the core)."""
    FA = _load('fixture_attempts', HERE / 'fixture_attempts.py')
    design = fx.git(repo, 'rev-parse', f'{declared}^').strip()
    path = Path(work) / 'st-dispatched' / 'integration.sqlite'
    path.parent.mkdir(parents=True)
    core = FA.AC.AgentServerCore()
    attempts = FA.FixtureAttempts(Path(work) / 'fixture-root')
    with store_module().open_store(path) as dispatched:
        for task in ('TASK-1', 'TASK-2'):
            attempts.attempt(dispatched, core, task, change=CHANGE, design_commit=design,
                             outcome_ref=f'outcome:{OUTCOME}')
    return path, RA.AttemptResolver(path, core, attempts.read_artifact)


def example_sources(work):
    """(repo, the dispatched attempts' store, the attempt resolver, the traced outcome) of the example under WORK."""
    repo, _store, declared, cited = build_example(work)
    store, resolver = build_dispatched(work, repo, declared)
    return repo, store, resolver, f'outcome:{OUTCOME}@{cited}'


def trace_example(sources, name):
    """The example's projection NAME (``fixture``: with the attempt resolver; ``real``: without it)."""
    repo, store, resolver, outcome = sources
    registry = R.build_registry(project=repo, backlog=FAKE_BACKLOG, conversations=conversations_path(repo),
                                attempts=resolver if name == 'fixture' else None)
    return run_trace(outcome, T.Authorities(registry), repo, store)


def example(work):
    """{'fixture': projection, 'real': projection} of the example built under WORK (``example_sources``), the
    outcome traced pinned at the commit that cites the Owner conversation store."""
    sources = example_sources(work)
    return {name: trace_example(sources, name) for name in FILES}


def dumps(data):
    return json.dumps(data, indent=2, ensure_ascii=False) + '\n'


def recorded():
    return {name: json.loads((EXAMPLES / FILES[name]).read_text(encoding='utf-8')) for name in FILES}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Build and trace the P-03.2 lineage example.')
    parser.add_argument('--record', action='store_true', help='write the projections into examples/')
    args = parser.parse_args(argv)
    try:
        # Without Dulwich every resolver answers PROJECT_UNAVAILABLE: never print, nor record,
        # such an example (decision 0014 section 9).
        fx.require_repository_access()
    except R.planning.repository_access.CannotRun as exc:
        print(f'ERROR {exc}', file=sys.stderr)
        return 2
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
