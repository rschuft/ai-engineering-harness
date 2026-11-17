"""The outcome card's projection fixtures (plan leaf U-04.2; the I1 integration design, slice 14): real
``outcome-projection/v1`` answers of ``GET /outcomes/{outcome_id}``, exported for the Owner host's card tests
(``apps/owner-host/src/areas/fixtures/outcome-projection/``).

Each answer is made the way U-04.1's own tests make theirs (``test_projection.py``): the attempt is written by the
dispatcher's own writers on a throwaway integration store (``test_projection.Base``: the checked-in fixture and live
declarations, their Agent Server answered by the fixture catalog's in-process core, the result published to E-05.4's
in-process Gitea fakes), the project, the Owner conversation store and Backlog.md's recorded output are
``test_projection.Outcome``'s, and the answer is the Integration process's own route (``app.create_app`` with a
``projection.Projection``, driven in process behind its session, Host and Origin guards): the status and the body
bytes it sends, parsed. Nothing in a fixture is written by hand.

``test_outcome_card_fixtures.py`` pins the committed files to the projection: each scenario is made again and its
answer must have the committed one's shape (every key, at every depth, with its value's type) and its decisive values
(the statuses, codes, authorities, failures, uncertainties and coverage), and ``schema.json`` must be the projection's
own constants. A change of the projection's schema therefore fails that test until the fixtures are exported again,
and the card's tests (``outcome-card.test.tsx``) then run against the new answers.

Export (the tools interpreter; a throwaway ``AIEH_DATA_ROOT`` and TEMP, as for the suite)::

    <tools python> -I -B integrations/ownerhost/tests/outcome_card_fixtures.py [--out DIR]
"""
from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import ownerhost_support as T  # noqa: E402

TP = T._load('test_projection', HERE / 'test_projection.py')
P, A, S, E = TP.P, T.A, T.S, TP.E
REPO = T.REPO
OUT = REPO / 'apps' / 'owner-host' / 'src' / 'areas' / 'fixtures' / 'outcome-projection'
GENERATOR = 'integrations/ownerhost/tests/outcome_card_fixtures.py'
OUTCOME_ID = TP.OUTCOME_ID
CONFIG = {'project_repository_id': 'aieh-d1-demo', 'backlog_command': 'backlog'}


class Exporter(TP.Base):
    """One scenario's bound fixture (``test_projection.Base``); ``runTest`` exists only so that it can be made."""

    def runTest(self):  # noqa: N802 - unittest's name
        pass


@contextlib.contextmanager
def backlog_of(sources):
    """Backlog.md's recorded output for SOURCES, answered in process (``test_projection.Route``'s patches)."""
    patch = E.in_process_backlog()
    patch.start()
    try:
        with mock.patch.dict(os.environ, {'FAKE_BACKLOG_SNAPSHOT': str(sources.snapshot)}), \
                mock.patch.object(P.planning, 'tool_argv', lambda spec: list(E.FAKE_BACKLOG)):
            yield
    finally:
        patch.stop()


class Served:
    """The Integration process's application for one scenario: its projection over CASE's integration store (STORE:
    True, None for none, or another path) and SOURCES' project and conversation store; a session enrolled in a
    throwaway conversation store (SESSIONS, when given, answers it instead: a server thread opens its own connection);
    PORT the port its Host guard expects and LIFESPAN its lifespan (an in-thread server's start signal). ``answer`` is one GET of ``/outcomes/<id>`` through every guard, in process; ``requests`` the
    application's log, one line per decided request."""

    def __init__(self, case, sources, *, store=True, configured=True, port=A.PORT, lifespan=None, sessions=None):
        self.session = T.Scratch(prefix='u42-')
        case.addCleanup(self.session.close)
        self.credential, _ = self.session.enroll(at=TP.NOW)
        self.sources = sources
        config = {**CONFIG, 'project_repository': str(sources.repo)} if configured and sources else None
        path = Path(case.store.path) if store is True else store
        self.projector = P.Projection(config, path, sources.conversations if sources else None,
                                      read_artifact=case.read_artifact)
        self.requests = []
        self.app = A.create_app(sessions or (lambda: self.session.store), port=port, clock=lambda: T.stamp(TP.NOW),
                                projector=self.projector, log=self.requests.append, lifespan=lifespan)

    def answer(self, path=f'/outcomes/{OUTCOME_ID}') -> dict:
        context = backlog_of(self.sources) if self.sources else contextlib.nullcontext()
        with context:
            status, _, body = T.call(self.app, 'GET', path, [T.HOST, ('origin', T.SHELL_ORIGIN),
                                                             (S.HEADER, self.credential)])
        return {'status': status, 'body': json.loads(body)}


def sources_for(case, snapshot='listed', statements=True):
    return TP.Outcome.build(case, snapshot, statements=statements)


# ---------------------------------------------------------------------------- the scenarios
# Each takes a fresh Exporter and returns its answers in order (one, or two for the reconnect pair). A fixture
# attempt's published answer is the reconnect pair's second.

def published_live(case):
    sources = sources_for(case)
    case.go(live=True)
    return [Served(case, sources).answer()]


def published_disclosed(case):
    sources = sources_for(case)
    result, _, published, _ = case.go()
    stop = {'kind': 'containment-stop', 'code': 'INSPECTION_FAILED', 'ref': f'attempt:{result.attempt_id}#x'}
    TP.AE.record_stop(case.store, result.operation_key, [stop], actor=TP.ACTOR, read_artifact=case.read_artifact)
    return [Served(case, sources).answer()]


def reconnect_running_then_published(case):
    """The same outcome read twice: while the host has verified the result and its publication is not yet recorded
    (running, RESULT_VERIFIED), and once it is published (succeeded, RESULT_PUBLISHED)."""
    sources = sources_for(case)
    answers = []

    def before_publication(gitea):
        answers.append(Served(case, sources).answer())
        return gitea
    case.go(gitea_fail=before_publication)
    answers.append(Served(case, sources).answer())
    return answers


def pending_created(case):
    sources = sources_for(case)
    case.fixture_attempt()
    return [Served(case, sources).answer()]


def running_turn_sent(case):
    sources = sources_for(case)
    result = case.fixture_attempt()
    case.turn(result)
    return [Served(case, sources).answer()]


def failed_refused_create(case):
    sources = sources_for(case)

    def refused(method, path, body=None, **kwargs):
        if (method, path) == ('POST', '/api/conversations'):
            return {'status': 401, 'body': {'detail': 'Unauthorized'}}
        return case.core(method, path, body, **kwargs)
    try:
        case.dispatched(TP.TA.Seam(refused, 'fixture'))
    except TP.di.DispatchRefused:
        pass
    return [Served(case, sources).answer()]


def unknown_create_outcome(case):
    sources = sources_for(case)

    def no_answer(method, path, body=None, **kwargs):
        if (method, path) == ('POST', '/api/conversations'):
            raise OSError('no answer')
        return case.core(method, path, body, **kwargs)
    try:
        case.dispatched(TP.TA.Seam(no_answer, 'fixture'))
    except OSError:
        pass
    return [Served(case, sources).answer()]


def unknown_label_missing(case):
    """A fixture-bound attempt whose turn journal lacks the label: unknown, its authority shown as neither."""
    sources = sources_for(case)
    result = case.fixture_attempt()
    case.turn(result, 'live')
    return [Served(case, sources).answer()]


def authority_unbound(case):
    """An admission refused because the pinned allowlist cannot be read: failed, the authority unknown."""
    sources = sources_for(case)
    (case.profiles / TP.TA.FIX / 'agent-server' / 'routes.json').unlink()
    try:
        case.dispatch(TP.TA.Seam(case.core, 'fixture'), TP.TA.provider('fixture'), manifest=case.fixture_manifest)
    except TP.di.DispatchRefused:
        pass
    return [Served(case, sources).answer()]


def unproven_after_restore(case):
    """A message sent after the backup the store was restored from: the attempt's records crossed a restore epoch
    (left open), so CREATED, which rests on an absence, is CREATED_UNPROVEN."""
    sources = sources_for(case)
    result = case.fixture_attempt()
    backup = case.store.backup(actor='owner')
    case.turn(result)
    case.restore(backup)
    return [Served(case, sources).answer()]


def no_attempt_unproven(case):
    """The attempt a restore lost: no attempt is recorded, and while an epoch exists that is NO_ATTEMPT_UNPROVEN."""
    sources = sources_for(case)
    case.store.reserve('u42/marker', {'x': 1}, actor=TP.ACTOR)
    backup = case.store.backup(actor='owner')
    case.fixture_attempt()
    case.restore(backup)
    return [Served(case, sources).answer()]


def lineage_failed(case):
    """Unresolved references: the Owner statements are not in the conversation store, and the task was deleted."""
    sources = sources_for(case, 'deleted', statements=False)
    case.fixture_attempt()
    return [Served(case, sources).answer()]


def store_unavailable(case):
    sources = sources_for(case)
    case.fixture_attempt()
    return [Served(case, sources, store=case.scratch / 'absent' / 'integration.sqlite').answer()]


def refused_unconfigured(case):
    return [Served(case, None, configured=False).answer()]


def refused_outcome_invalid(case):
    sources = sources_for(case)
    return [Served(case, sources).answer('/outcomes/not-an-outcome')]


SCENARIOS = {
    'published-live': (published_live, 'a live-declared attempt run to a published result receipt '
                                       '(test_projection.EndToEnd)'),
    'published-disclosed': (published_disclosed, 'a stop recorded after the published result '
                                                 '(test_projection.MoreRows)'),
    'reconnect': (reconnect_running_then_published, 'the same outcome before and after its publication '
                                                    '(test_projection.StateTable, EndToEnd)'),
    'pending-created': (pending_created, 'an attempt created, nothing later recorded (test_projection.StateTable)'),
    'running-turn-sent': (running_turn_sent, 'the message recorded delivered (test_projection.Labels)'),
    'failed-refused-create': (failed_refused_create, 'the create refused (test_projection.StateTable)'),
    'unknown-create-outcome': (unknown_create_outcome, 'the create\'s answer lost (test_projection.StateTable)'),
    'unknown-label-missing': (unknown_label_missing, 'a fixture attempt\'s turn journal without the label '
                                                     '(test_projection.Labels)'),
    'authority-unbound': (authority_unbound, 'the pinned allowlist unreadable (test_projection.Labels)'),
    'unproven-after-restore': (unproven_after_restore, 'a restore epoch open over the attempt '
                                                       '(test_projection.Restore)'),
    'no-attempt-unproven': (no_attempt_unproven, 'the attempt a restore lost (test_projection.Restore)'),
    'lineage-failed': (lineage_failed, 'Owner statements missing and the task deleted (test_projection.Outcome)'),
    'store-unavailable': (store_unavailable, 'the integration store unreadable (test_projection.Outcome)'),
    'refused-unconfigured': (refused_unconfigured, 'no project configured (test_projection.Route)'),
    'refused-outcome-invalid': (refused_outcome_invalid, 'a path that names no outcome (test_projection.Route)'),
}


def generate(name: str) -> list[dict]:
    """The answers of scenario NAME, made on a fresh fixture (Exporter.setUpClass must have run)."""
    function, _ = SCENARIOS[name]
    case = Exporter()
    case.setUp()
    try:
        answers = function(case)
        local = [str(case.scratch), tempfile.gettempdir(), str(Path.home())]
    finally:
        case.doCleanups()
    for answer in answers:
        held = [s for s in TP.strings(answer) for root in local if root and root.lower() in s.lower()]
        if held:
            raise AssertionError(f'{name}: a local path is in the answer: {held[0][:200]!r}')
    return answers


def schema() -> dict:
    """The projection's own constants the card reads (projection.py)."""
    return {'format': P.FORMAT, 'statuses': list(P.STATUSES), 'codes': list(P.CODES), 'unprovenSuffix': P.UNPROVEN,
            'noAttemptCodes': ['NO_ATTEMPT', 'NO_ATTEMPT' + P.UNPROVEN, 'STORE_UNAVAILABLE'],
            'fixtureAuthority': P.FIXTURE_AUTHORITY, 'coverage': dict(P.COVERAGE),
            'refusals': {code: P.STATUS[code] for code in P.STATUS},
            'sessionDetail': {'refused': P.SESSION_ACCESS_UNAVAILABLE, 'canvasPath': P.CANVAS_CONVERSATION_PATH,
                              'authority': P.FIXTURE}}


def document(name: str, answers: list[dict]) -> dict:
    return {'scenario': name, 'source': SCENARIOS[name][1], 'generatedBy': GENERATOR,
            'route': 'GET /outcomes/{outcome_id}', 'answers': answers}


def dumps(value) -> str:
    return json.dumps(value, indent=1, ensure_ascii=False) + '\n'


# ---------------------------------------------------------------------------- what the cross-check compares

def shape(value):
    """Every key at every depth with its value's type; a list is the set of its elements' shapes."""
    if isinstance(value, dict):
        return {key: shape(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        shapes = []
        for item in value:
            if (s := shape(item)) not in shapes:
                shapes.append(s)
        return ['list', sorted(shapes, key=lambda s: json.dumps(s, sort_keys=True))]
    return type(value).__name__


def bases(attempt: dict) -> list:
    """Every evidence and result entry's basis (verified, reported), by where it is: the card groups them by it."""
    found = []
    for part in ('evidence', 'result'):
        for key, entry in sorted((attempt.get(part) or {}).items()):
            if isinstance(entry, dict) and 'basis' in entry:
                found.append((part, key, entry['basis']))
    return found


def decisive(answer: dict) -> dict:
    """The values the card's display rests on."""
    body = answer['body']
    if answer['status'] != 200:
        return {'status': answer['status'], 'code': body.get('code'), 'keys': sorted(body)}
    return {
        'status': 200, 'format': body['format'], 'outcome': body['outcome'], 'lineageVerdict': body['lineageVerdict'],
        'tasks': [(t['reference'], t['resolution'], t['reachedThrough'], t['execution']['status'],
                   t['execution']['code']) for t in body['tasks']],
        'attempts': [(a['executionStatus'], a['executionCode'], a['authority']['shown'], a['authority']['bound'],
                      a['authority']['code'], a['authority'].get('reason'), a['authority'].get('detail'),
                      a.get('restoredRow'), len(a.get('disclosed') or ()),
                      a['evidence'] is not None, a['result']['verified'] is not None,
                      a['result']['reported'] is not None, bases(a), a['sessionDetail']) for a in body['attempts']],
        'failures': sorted((f['role'], f['outcome'], f['code']) for f in body['failures']),
        'uncertainties': sorted((u['reason'], u['code']) for u in body['lineageUncertainties']),
        'coverage': body['coverage'],
        'integrationStore': body['sources']['integrationStore'] == 'read',
        'restoreEpochOpen': body['sources']['restoreEpochOpen'],
    }


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--out', type=Path, default=OUT)
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    Exporter.setUpClass()
    try:
        for name in SCENARIOS:
            (args.out / f'{name}.json').write_text(dumps(document(name, generate(name))), encoding='utf-8',
                                                   newline='\n')
            print(f'wrote {name}.json')
    finally:
        Exporter.tearDownClass()
    (args.out / 'schema.json').write_text(dumps({'generatedBy': GENERATOR, **schema()}), encoding='utf-8',
                                          newline='\n')
    print('wrote schema.json')
    return 0


if __name__ == '__main__':
    sys.exit(main())
