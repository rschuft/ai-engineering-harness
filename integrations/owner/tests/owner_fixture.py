"""Fixtures of the acceptance recorder (plan leaf P-04.1): a throwaway project repository and the
recorded example decision record.

``build_project(directory)`` creates, with git and a fixed identity and date (so that its commit
id is reproducible), a project repository holding two intent-driven OpenSpec changes copied byte
for byte from the P-01.2 recording (``tools/tests/fixtures/intent_qualification/openspec/``):

- ``qual-05-api-rate-limiting``: Objective O1 ``authority: proposed``, no outcome id;
- ``qual-02-search-freshness``: O1 already ``accepted`` by hand (``conversation:qual-02/message-2``,
  the P-01.2 fixture standing in for the Owner), with no outcome id.

It is built once per process and copied for each caller (``two_task_fixture.golden``).

``example(work)`` records one acceptance of O1 of qual-05 on that repository with a fixed clock,
nonce and ids, and returns the decision record; ``--record`` writes it to
``fixtures/accept-objective.decision.json``. Every statement here is **synthetic**: it stands in
for an Owner statement and is no Owner decision.

    <tools python> -I -B integrations/owner/tests/owner_fixture.py [--record]
"""
import argparse
import datetime
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OWNER = HERE.parent
REPO = OWNER.parents[1]
FIXTURES = HERE / 'fixtures'
EXAMPLE = FIXTURES / 'accept-objective.decision.json'
INTENT_OPENSPEC = REPO / 'tools' / 'tests' / 'fixtures' / 'intent_qualification' / 'openspec'
CHANGES = ('qual-05-api-rate-limiting', 'qual-02-search-freshness')
PROPOSED = CHANGES[0]
HAND_ACCEPTED = CHANGES[1]
MESSAGE = 'OpenSpec changes qual-05 and qual-02 (the acceptance recorder fixture)'


def _load(name, path):
    import importlib.util
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


# The recorder first, so that the planning adapter and the repository module are one instance each.
A = _load('acceptance_recorder', OWNER / 'acceptance_recorder.py')
D = A.D
sys.path.insert(0, str(REPO / 'integrations' / 'planning' / 'tests'))
import two_task_fixture as fx  # noqa: E402

NOW = datetime.datetime(2026, 11, 10, 12, 0, 0, tzinfo=datetime.timezone.utc)
NONCE = 'f1' * 16
OUTCOME = '0d1f2e3c-4b5a-4c6d-8e7f-001122334455'
DECISION = '9e8d7c6b-5a49-4382-a716-5f4e3d2c1b0a'
IDENTITY = 'Acceptance Recorder Fixture <recorder@example.invalid>'
RECORDED_BY = 'agent:fixture-transcriber'


def statement(**changes):
    """A SYNTHETIC statement standing in for the Owner's acceptance (no Owner decision)."""
    return {'text': 'SYNTHETIC FIXTURE, not an Owner decision: I accept O1 as written.', 'attributedTo': 'owner',
            'channel': 'main-session', 'reference': 'conversation:fixture-owner/message-2', **changes}


def project_files():
    files = {'README.md': b'Throwaway project repository of the P-04.1 acceptance-recorder fixture.\n',
             'openspec/config.yaml': (INTENT_OPENSPEC / 'config.yaml').read_bytes()}
    for change in CHANGES:
        base = INTENT_OPENSPEC / 'changes' / change
        for path in sorted(base.rglob('*')):
            if path.is_file():
                files[f'openspec/changes/{change}/{path.relative_to(base).as_posix()}'] = path.read_bytes()
    return files


def _build(repo, files):
    Path(repo).mkdir(parents=True)
    fx.git(repo, 'init', '--quiet', '-b', 'main')
    fx.write(repo, files)
    return fx.commit_all(repo, MESSAGE)


def build_project(repo):
    """Create the project repository at REPO (which must not exist); return its commit id."""
    files = project_files()
    key = fx.input_digest('owner-project/1', files, MESSAGE, fx.GIT_ENV)
    return fx.golden(repo, key, lambda directory: _build(directory, files))


def example(work):
    """The decision record of one recorded acceptance with fixed clock, nonce and ids."""
    repo = Path(work) / 'p'
    build_project(repo)
    with fx.ceiling(work):
        challenge = A.prepare(repo, PROPOSED, 'O1', now=NOW, nonce=NONCE)
        result = A.record(repo, challenge, statement(), recorded_by=RECORDED_BY, identity=IDENTITY,
                          now=NOW + datetime.timedelta(minutes=5), new_outcome=lambda: OUTCOME,
                          new_decision_id=lambda: DECISION)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description='Build the acceptance-recorder example decision record.')
    parser.add_argument('--record', action='store_true', help=f'write it to {EXAMPLE.relative_to(REPO).as_posix()}')
    args = parser.parse_args(argv)
    fx.require_repository_access()
    work = Path(tempfile.mkdtemp(prefix='ow-'))
    try:
        text = D.dumps(example(work)['decision'])
    finally:
        fx.rmtree(work)
    if fx.MACHINE_PATH.search(text):
        print('ERROR the example names a machine path', file=sys.stderr)
        return 1
    if args.record:
        EXAMPLE.write_text(text, encoding='utf-8', newline='\n')
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stdout.write(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
