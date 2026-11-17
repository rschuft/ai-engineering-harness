"""The outcome projection of the Integration process (plan leaf U-04.1; the I1 integration design, R6, R11 and slice 12;
decisions 0013, 0024, 0025 and 0026).

One read-only, typed view of an outcome (``outcome-projection/v1``): the lineage traversal from the outcome id over
the project repository, Backlog.md's two read commands and the Owner conversation store (the objective, the design,
the tasks and the statements, ``lineage-projection/v1`` as it is), joined with each attempt's **observed** state, read
from the dispatcher's own records in the integration store, and the attempt's result receipt joined as evidence by
reference.

**Execution state.** An attempt's status is decided by the state table of README.md ("Outcome projection"), from the
dispatcher's records only: the typed attempt and its transitions, and its records under
``dispatch/attempt/<attempt id>/`` (the turn journal, the launch receipt, the delivery, pull and intake receipts, the
result journal and its receipt, the end journal and its record, the stop receipts). Never from an agent's exit claim,
and never from an Agent Server, real or fixture: this module has no transport and asks nobody (decision 0013 point 1).
What those records do not determine is ``unknown``. A report (what the attempt itself printed or claimed) never sets
a status; it is shown as ``reported`` beside what the host ``verified``.

**The authority** (R11). Each attempt's bound authority is read from its reservation's pinned route allowlist
(``bound_authority.py``, which the dispatcher's own reader is pinned to by a test), and every label the dispatcher
wrote on the attempt's records must agree with it: a fixture-bound attempt's labelled records must carry
``authority: fixture``, and a live-bound attempt's records carry none. Otherwise the attempt is ``unknown`` with a
stable code and its authority is shown as neither (``unknown``).

**Failures and coverage.** An unresolved objective, statement (``message``, ``conversation``) or task (``work``,
archived ones included: Backlog.md's ``task view`` reads an archived task) reference is a failure, and the
projection's lineage verdict is ``failed``. Backlog.md 1.55.3's ``task list`` cannot enumerate archived tasks, so a task
archived with no attempt citing the outcome is not reached: the projection says so in its ``coverage`` field, always.

Read-only throughout: the integration store and the Owner conversation store are opened read-only (SQLite
``mode=ro``, ``query_only``); git is read through the repository-access module (no process); Backlog.md runs only
``task list`` and ``task view``; OpenSpec never runs.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Callable

HERE = Path(os.path.realpath(__file__)).parent
REPO = HERE.parents[1]


def _load(name: str, path: Path):
    if (module := sys.modules.get(name)) is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = sys.modules[name] = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except BaseException:
            del sys.modules[name]
            raise
    return module


binding = _load('aieh_ownerhost_bound_authority', HERE / 'bound_authority.py')
capture = _load('aieh_ownerhost_capture', HERE / 'capture.py')
trace_mod = _load('lineage_trace', REPO / 'integrations' / 'lineage' / 'lineage_trace.py')
R, L = trace_mod.resolve_mod, trace_mod.L
planning = trace_mod.planning
store_mod = binding.integration_store

FORMAT = 'outcome-projection/v1'
PENDING, RUNNING, FAILED, UNKNOWN, SUCCEEDED = 'pending', 'running', 'failed', 'unknown', 'succeeded'
STATUSES = (PENDING, RUNNING, FAILED, UNKNOWN, SUCCEEDED)
REPORTED, VERIFIED = 'reported', 'verified'
LIVE, FIXTURE = binding.LIVE, binding.FIXTURE

# The dispatcher's records this projection reads (integrations/dispatch: attempt_run, launch_gate, result_path,
# attempt_end; tests/test_projection.py pins each equal to its writer's constant).
RECORD_PREFIX = 'dispatch/attempt/'
FORMATS = {
    'turn': 'ai-engineering-harness/dispatch/attempt-turn/v1',
    'launch': 'ai-engineering-harness/dispatch/attempt-launch/v1',
    'delivery': 'ai-engineering-harness/dispatch/attempt-delivery/v1',
    'pull': 'ai-engineering-harness/dispatch/attempt-pull/v1',
    'intake': 'ai-engineering-harness/dispatch/attempt-intake/v1',
    'result': 'ai-engineering-harness/dispatch/attempt-result-journal/v1',
    'end': 'ai-engineering-harness/dispatch/attempt-end-journal/v1',
    'stop': 'ai-engineering-harness/dispatch/attempt-stop/v1',
}
RESULT_RECEIPT_FORMAT = 'ai-engineering-harness/dispatch/result-receipt/v1'
END_FORMAT = 'ai-engineering-harness/dispatch/attempt-end/v1'
LAUNCHED, NOT_LAUNCHED = 'launched', 'not-launched'
EXECUTION_REF_PREFIX = 'openhands:conversation/'
# R11: the records whose writers label them when the attempt's bound authority is not live (E-01.8): each one's
# intent (the result journal's at ``result.authority``), the result receipt and the end record, and every transition
# of the typed attempt after its reservation.
LABELLED = tuple(FORMATS)
LABELLED_DETAILS = {'result': RESULT_RECEIPT_FORMAT, 'end': END_FORMAT}
TESTS_LABEL = 'the attempt\'s own tests, run in its container: not independent CI'

# The authority row (0) and the state table's codes (README.md, "Outcome projection").
AUTHORITY_CODES = ('ATTEMPT_AUTHORITY_UNBOUND', 'ATTEMPT_LABEL_MISSING', 'ATTEMPT_LABEL_MISMATCH',
                   'ATTEMPT_LABEL_ON_LIVE')
CODES = (*AUTHORITY_CODES, 'RECORD_UNREADABLE', 'ATTEMPT_RESERVED', 'CREATE_SENT', 'CREATE_OUTCOME_UNKNOWN',
         'ATTEMPT_FAILED', 'LAUNCH_NOT_LAUNCHED', 'ATTEMPT_STOPPED', 'ATTEMPT_ENDED', 'ATTEMPT_END_UNSETTLED',
         'ATTEMPT_ENDING', 'RESULT_PUBLISHED', 'RESULT_FAILED', 'RESULT_WRITE_UNSETTLED', 'RESULT_PUBLISHING',
         'RESULT_VERIFIED', 'RESULT_DELIVERED', 'TURN_OUTCOME_UNKNOWN', 'TURN_FAILED', 'TURN_SENT', 'MESSAGE_SENDING',
         'MESSAGE_RESERVED', 'LAUNCHED', 'CREATED', 'NO_ATTEMPT', 'STORE_UNAVAILABLE', 'RESULT_RECEIPT_UNSETTLED')
# Absence across a restore (decision 0004 point 7): a pending or running row rests on the absence of a later record. For
# an attempt whose reservation is part of a history a restore brought back (its reservation event at or below some restore
# epoch's backup high-water mark, open or closed), the records cannot prove that absence: the row is unknown, its code the
# row's own with this suffix (ATTEMPT_RESERVED -> ATTEMPT_RESERVED_UNPROVEN, CREATED -> CREATED_UNPROVEN, ...); and while
# any restore epoch exists, a task with no recorded attempt is NO_ATTEMPT_UNPROVEN (the reservation is exactly the
# receipt a restore can lose).
UNPROVEN = '_UNPROVEN'
FIXTURE_AUTHORITY = 'FIXTURE_AUTHORITY'

# The coverage limit (the engineering manager's ruling 4, as ruled on the STOP): stated on every projection.
BACKLOG_PIN = 'Backlog.md 1.55.3'
COVERAGE = {'archivedTasksEnumerable': False, 'code': 'ARCHIVED_TASKS_NOT_ENUMERABLE',
            'basis': f'{BACKLOG_PIN} task list --json',
            'detail': 'task list --json does not list an archived task, and no read command enumerates one; '
                      'task view <id> --json reads it. A task is reached when Backlog.md lists it (its references '
                      'cite the outcome or its design) or when an attempt reservation cites it and the outcome, '
                      'archived or not: a task archived with no attempt citing the outcome is not shown.'}
FAILURE_ROLES = ('objective', 'statement', 'work')


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _loads(text):
    if text is None:
        return None
    try:
        return binding.strict_loads(text)
    except ValueError:
        return _BAD


_BAD = object()          # a record's JSON that does not parse


class Record:
    """One record of the store: its key, kind (the part after ``dispatch/attempt/<id>/``, or ``typed``), state,
    parsed intent and its transitions [(seq, event id, to state, reason, parsed detail)]."""

    def __init__(self, reservation, events, kind):
        self.key, self.kind, self.state = reservation.operation_key, kind, reservation.state
        self.intent = _loads(reservation.intent_json)
        self.events = [(e.seq, e.event_id, e.to_state, e.reason, _loads(e.detail_json)) for e in events]

    def detail(self, to_state):
        """The detail of the last move into TO_STATE (None when there is none)."""
        for _seq, _id, to, _reason, detail in reversed(self.events):
            if to == to_state:
                return detail
        return None

    def shown(self) -> dict:
        seq, event_id, to, _reason, _detail = self.events[-1] if self.events else (None, None, None, None, None)
        return {'record': self.key, 'state': self.state, 'eventSeq': seq, 'eventId': event_id}

    def problem(self):
        """Why this record is outside what the table names, or None."""
        if self.state not in store_mod.STATES:
            return f'{self.key} is in state {self.state!r}'
        if self.intent is _BAD or any(d is _BAD for *_, d in self.events):
            return f'{self.key} holds a record that is not strict JSON'
        if self.kind in FORMATS and (not isinstance(self.intent, dict) or self.intent.get('format') != FORMATS[self.kind]):
            return f'{self.key} is not {FORMATS[self.kind]}'
        if self.kind in LABELLED_DETAILS and self.state == 'confirmed':
            detail = self.detail('confirmed')
            if not isinstance(detail, dict) or detail.get('format') != LABELLED_DETAILS[self.kind]:
                return f'{self.key} is confirmed without its {LABELLED_DETAILS[self.kind]}'
        return None


def records_of(rows, events_of, attempt_id: str) -> dict:
    """{kind: Record} of the attempt ATTEMPT_ID's records among ROWS, for the kinds the table reads (one each: their
    key is ``dispatch/attempt/<id>/<kind>``); ``stop`` holds the stop receipts and ``other`` every other record of the
    attempt (``auth-cause``, ``inference-revocation/<n>``, ...), each kept whole under its full key suffix, so that
    no two collide and every one is label-checked."""
    prefix = f'{RECORD_PREFIX}{attempt_id}/'
    found = {'stop': [], 'other': []}
    for row in rows:
        if row.operation_key.startswith(prefix):
            suffix = row.operation_key[len(prefix):]
            kind = suffix.split('/')[0]
            record = Record(row, events_of(row.operation_key), kind)
            if kind == 'stop':
                found['stop'].append(record)
            elif kind in FORMATS and suffix == kind:
                found[kind] = record
            else:
                found['other'].append(record)
    return found


def every(records: dict) -> list:
    """Every record of RECORDS (``records_of``), the table's kinds first."""
    return [r for k, r in records.items() if k not in ('stop', 'other')] + records['stop'] + records['other']


def _labels_of(record: Record):
    """[(where, value)] of every label on RECORD (its intent's, the result journal's at ``result.authority``, and its
    transitions' details), and whether each place the writers label carries one."""
    found, carried = [], True
    intent = record.intent if isinstance(record.intent, dict) else {}
    if record.kind == 'result':
        held = intent.get('result') if isinstance(intent.get('result'), dict) else {}
        place = 'result.authority'
    else:
        held, place = intent, 'authority'
    if 'authority' in held:
        found.append((f'{record.key} intent {place}', held['authority']))
    elif record.kind in LABELLED:
        carried = False
    if 'authority' in intent and record.kind == 'result':
        found.append((f'{record.key} intent authority', intent['authority']))
    if record.kind == 'intake':
        # the verified result's own record (attempt_run.VerifiedResult.to_json) carries the label too
        nested = intent.get('record') if isinstance(intent.get('record'), dict) else {}
        if 'authority' in nested:
            found.append((f'{record.key} intent record.authority', nested['authority']))
        else:
            carried = False
    for seq, _id, to, _reason, detail in record.events:
        if isinstance(detail, dict) and 'authority' in detail:
            found.append((f'{record.key} #{seq} {to}', detail['authority']))
        elif record.kind == 'typed' and seq != 0:
            carried = False
        elif record.kind in LABELLED_DETAILS and to == 'confirmed' and record.state == 'confirmed':
            carried = False
    return found, carried


def label_rule(bound: str, typed: Record, records: dict):
    """R11 over the attempt's records: (code, detail) when a label disagrees with the binding, else None."""
    found, missing = [], []
    for record in [typed, *every(records)]:
        labels, carried = _labels_of(record)
        found += labels
        if not carried:
            missing.append(record.key)
    if bound == LIVE:
        if found:
            return 'ATTEMPT_LABEL_ON_LIVE', f'the attempt is bound live and {found[0][0]} carries a label'
        return None
    other = [(where, value) for where, value in found if value != bound]
    if other:
        return 'ATTEMPT_LABEL_MISMATCH', f'the attempt is bound {bound} and {other[0][0]} carries {other[0][1]!r}'
    if missing:
        return 'ATTEMPT_LABEL_MISSING', f'the attempt is bound {bound} and {missing[0]} lacks the label'
    return None


def _decide(status, code, shown, detail='', **extra):
    return {'executionStatus': status, 'executionCode': code, 'shownBy': shown, 'detail': detail, **extra}


def state_of(typed: Record, records: dict, *, crossed: tuple = ()) -> dict:
    """The state table (README.md) over the typed attempt and its records. CROSSED: the restore epochs (their ids) whose
    restored history holds the attempt's reservation; with any, a pending or running row, which rests on the absence
    of a later record, is unknown (``<code>_UNPROVEN``)."""
    decided = _rows(typed, records)
    if crossed and decided['executionStatus'] in (PENDING, RUNNING):
        return {**decided, 'executionStatus': UNKNOWN, 'executionCode': decided['executionCode'] + UNPROVEN,
                'restoredRow': decided['executionCode'], 'restoreEpochs': list(crossed),
                'detail': 'the attempt\'s records crossed a restore (epoch '
                          f'{", ".join(str(e) for e in crossed)}): the restored history proves no absence '
                          f'({decided["detail"]})'}
    return decided


def crossing(reserved_event_id, epochs) -> tuple:
    """The ids of the restore EPOCHS (``ReadOnlyIntegrationStore.restore_epochs``) whose restored history holds a
    reservation of event RESERVED_EVENT_ID: its event is at or below the epoch's backup high-water mark. Ordered by the
    store's own event ids, never a clock. An unknown event id crosses every epoch."""
    return tuple(e['epochId'] for e in epochs
                 if reserved_event_id is None or e['backupHighWater'] >= reserved_event_id)


def _unsettled(record: Record):
    return record.state in ('unknown', 'failed')


def _rows(typed: Record, records: dict) -> dict:
    for record in [typed, *every(records)]:
        problem = record.problem()
        if problem:
            return _decide(UNKNOWN, 'RECORD_UNREADABLE', record.shown(), problem)
    state = typed.state
    if state == 'reserved':
        return _decide(PENDING, 'ATTEMPT_RESERVED', typed.shown(), 'reserved: no create is recorded')
    if state == 'dispatched':
        return _decide(RUNNING, 'CREATE_SENT', typed.shown(), 'the create is recorded sent; its answer is not recorded')
    if state == 'unknown':
        return _decide(UNKNOWN, 'CREATE_OUTCOME_UNKNOWN', typed.shown(), 'the create\'s answer was lost')
    if state == 'failed':
        detail = typed.detail('failed')
        code = detail.get('code') if isinstance(detail, dict) else None
        return _decide(FAILED, 'ATTEMPT_FAILED', typed.shown(), f'the attempt failed ({code or typed.events[-1][3]})',
                       cause=code or typed.events[-1][3])
    if state != 'confirmed':
        return _decide(UNKNOWN, 'RECORD_UNREADABLE', typed.shown(), f'the typed attempt is {state!r}')
    launch, end, result = records.get('launch'), records.get('end'), records.get('result')
    not_launched = launch is not None and launch.state == 'confirmed' and launch.intent.get('verdict') == NOT_LAUNCHED
    stops = [r for r in records['stop'] if r.state == 'confirmed']
    if result is not None and result.state == 'confirmed':
        # a published result is an observed effect: whatever is recorded beside it is disclosed, never in its place
        disclosed = [r.shown() for r in ([launch] if not_launched else []) + stops + ([end] if end else [])]
        return _decide(SUCCEEDED, 'RESULT_PUBLISHED', result.shown(),
                       'the host verified the result and read its branch and draft pull request back',
                       **({'disclosed': disclosed} if disclosed else {}))
    if not_launched:
        return _decide(FAILED, 'LAUNCH_NOT_LAUNCHED', launch.shown(), 'the launch gate did not launch it',
                       problems=len(launch.intent.get('problems') or ()))
    if stops:
        return _decide(FAILED, 'ATTEMPT_STOPPED', stops[0].shown(), 'the dispatcher recorded a stop',
                       stops=[{'kind': r.intent.get('kind'), 'code': r.intent.get('code')} for r in stops])
    if end is not None:
        if end.state == 'confirmed':
            record = end.detail('confirmed')
            surfaced = record.get('surfaced') if isinstance(record.get('surfaced'), dict) else {}
            return _decide(FAILED, 'ATTEMPT_ENDED', end.shown(), 'the attempt was ended',
                           end={'trigger': record.get('trigger'), 'classification': record.get('classification'),
                                'causes': record.get('causes'),
                                'executionStatus': surfaced.get('executionStatus')})
        if end.state == 'unknown':
            return _decide(UNKNOWN, 'ATTEMPT_END_UNSETTLED', end.shown(), 'the end\'s outcome was not recorded')
        if end.state in ('reserved', 'dispatched'):
            return _decide(RUNNING, 'ATTEMPT_ENDING', end.shown(), 'the attempt is being ended')
        return _decide(UNKNOWN, 'RECORD_UNREADABLE', end.shown(), f'the end journal is {end.state}')
    if result is not None:
        if result.state == 'failed':
            detail = result.detail('failed')
            code = detail.get('code') if isinstance(detail, dict) else None
            return _decide(FAILED, 'RESULT_FAILED', result.shown(), f'the result path failed ({code})', cause=code)
        if result.state == 'unknown':
            return _decide(UNKNOWN, 'RESULT_WRITE_UNSETTLED', result.shown(),
                           'a write of the result path was refused or its answer lost')
        if result.state == 'dispatched':
            return _decide(RUNNING, 'RESULT_PUBLISHING', result.shown(), 'the result is being published')
        return _decide(RUNNING, 'RESULT_VERIFIED', result.shown(),
                       'the host verified the result; no publication is recorded')
    for kind in ('intake', 'pull', 'delivery'):
        receipt = records.get(kind)
        if receipt is None:
            continue
        if _unsettled(receipt):
            return _decide(UNKNOWN, 'RESULT_RECEIPT_UNSETTLED', receipt.shown(),
                           f'the {kind} receipt is {receipt.state}: what the result step did is not recorded')
        if kind == 'intake':
            return _decide(RUNNING, 'RESULT_VERIFIED', receipt.shown(),
                           'the host verified the result; no publication is recorded')
        return _decide(RUNNING, 'RESULT_DELIVERED', receipt.shown(),
                       'the result is recorded delivered (reported), not verified by the host')
    turn = records.get('turn')
    if turn is not None:
        if turn.state == 'unknown':
            return _decide(UNKNOWN, 'TURN_OUTCOME_UNKNOWN', turn.shown(), 'the message\'s answer was lost')
        if turn.state == 'failed':
            return _decide(FAILED, 'TURN_FAILED', turn.shown(), f'the message failed ({turn.events[-1][3]})',
                           cause=turn.events[-1][3])
        if turn.state == 'confirmed':
            return _decide(RUNNING, 'TURN_SENT', turn.shown(),
                           'the message is recorded delivered; no result is recorded')
        if turn.state == 'dispatched':
            return _decide(RUNNING, 'MESSAGE_SENDING', turn.shown(),
                           'the message is recorded being sent; its answer is not recorded')
        return _decide(PENDING, 'MESSAGE_RESERVED', turn.shown(),
                       'the turn journal is reserved; no message is recorded sent')
    if launch is not None and launch.state == 'confirmed' and launch.intent.get('verdict') == LAUNCHED:
        return _decide(PENDING, 'LAUNCHED', launch.shown(), 'launched; no message is recorded')
    return _decide(PENDING, 'CREATED', typed.shown(), 'the create is recorded answered; no later record')


def _digest(value) -> dict | None:
    return {'sha256': value.get('sha256'), 'bytes': value.get('bytes', value.get('size'))} \
        if isinstance(value, dict) else None


def result_of(records: dict) -> dict:
    """The result's claims, each with its basis: what the attempt reported, and what the host verified."""
    out = {REPORTED: None, VERIFIED: None, 'tests': None}
    delivery = records.get('delivery')
    if delivery is not None and isinstance(delivery.intent, dict):
        out[REPORTED] = {'basis': REPORTED, 'record': delivery.key, 'commit': delivery.intent.get('commit'),
                         'bundle': _digest(delivery.intent.get('bundle')),
                         'statement': 'the commit and bundle digest RESULT printed in the container'}
    intake = records.get('intake')
    record = intake.intent.get('record') if intake is not None and isinstance(intake.intent, dict) else None
    if isinstance(record, dict):
        out[VERIFIED] = {'basis': VERIFIED, 'record': intake.key, 'commit': record.get('commit'),
                         'tree': record.get('tree'), 'base': record.get('base'),
                         'bundle': _digest(record.get('bundle')),
                         'statement': 'the host computed the commit over the pulled bundle and checked its tree'}
        tests = record.get('tests') if isinstance(record.get('tests'), dict) else {}
        out['tests'] = {'basis': REPORTED, 'record': intake.key, 'status': tests.get('status'),
                        'command': tests.get('command'), 'output': _digest(tests.get('output')),
                        'statement': TESTS_LABEL}
    return out


def evidence_of(records: dict) -> dict | None:
    """The result receipt (E-05.4's ``result-receipt/v1``) joined as evidence: the commit, the diff and the test output
    by reference and digest, never their text."""
    result = records.get('result')
    if result is None or result.state != 'confirmed':
        return None
    receipt = result.detail('confirmed')
    if not isinstance(receipt, dict) or receipt.get('format') != RESULT_RECEIPT_FORMAT:
        return None
    seq = next((s for s, _id, to, *_ in reversed(result.events) if to == 'confirmed'), None)
    tests = receipt.get('tests') if isinstance(receipt.get('tests'), dict) else {}
    report = receipt.get('report') if isinstance(receipt.get('report'), dict) else {}
    pull = receipt.get('pullRequest') if isinstance(receipt.get('pullRequest'), dict) else {}
    return {
        'receipt': {'record': result.key, 'format': RESULT_RECEIPT_FORMAT, 'eventSeq': seq,
                    'sha256': _sha256(store_mod.storecore.canonical_json(receipt))},
        'commit': {'basis': VERIFIED, 'reference': receipt.get('resultRef'), 'commit': receipt.get('commit'),
                   'branch': receipt.get('branch')},
        'diff': {'basis': VERIFIED, 'from': receipt.get('baseRef'), 'to': receipt.get('resultRef'),
                 'ownerReport': {'jsonSha256': report.get('jsonSha256'),
                                 'markdownSha256': report.get('markdownSha256')},
                 'statement': 'the diff from the base to the result commit; the Owner report that shows it, by '
                              'digest'},
        'testOutput': {'basis': REPORTED, 'output': _digest(tests.get('outputDigest')), 'status': tests.get('status'),
                       'outcome': tests.get('outcome'), 'statement': TESTS_LABEL},
        'pullRequest': {'basis': VERIFIED, 'number': pull.get('number'), 'url': pull.get('url'),
                        'state': pull.get('state'), 'draft': pull.get('draft'), 'bodySha256': pull.get('bodySha256')},
        'bundle': _digest(receipt.get('bundle')),
        'lineage': {k: receipt.get(k) for k in ('workRef', 'outcomeRef', 'executionRef', 'designRevision')},
    }


def attempt_view(reservation, rows, events_of, *, identity=None, read_artifact=None, epochs=()) -> dict:
    """The typed status of the attempt RESERVATION from its records among ROWS (EVENTS_OF answers a key's
    transitions), with its authority, its result's claims and its evidence."""
    key = reservation.operation_key
    attempt_id, conversation = store_mod.attempt_id_for(key), reservation.conversation_id
    typed = Record(reservation, events_of(key), 'typed')
    records = records_of(rows, events_of, attempt_id)
    view = {'operationKey': key, 'attemptId': attempt_id, 'conversationId': conversation,
            'executionRef': f'{EXECUTION_REF_PREFIX}{conversation}',
            'workId': identity.work_id if identity else None, 'stage': identity.stage if identity else None,
            'ordinal': identity.ordinal if identity else None,
            'reservedEventId': typed.events[0][1] if typed.events else None,
            'records': sorted(r.key for r in every(records))}
    decided = state_of(typed, records, crossed=crossing(view['reservedEventId'], epochs))
    try:
        bound = binding.bound_authority(reservation, read_artifact)
    except binding.Unbound as exc:
        bound, unbound = None, exc
    if bound is None:
        view['authority'] = {'shown': UNKNOWN, 'bound': None, 'code': 'ATTEMPT_AUTHORITY_UNBOUND',
                             'reason': unbound.code, 'detail': unbound.detail}
        if decided['executionStatus'] != FAILED or decided['executionCode'] != 'ATTEMPT_FAILED':
            # a failed attempt stays failed (nothing it did can be shown as live or fixture); anything else is unknown
            decided = _decide(UNKNOWN, 'ATTEMPT_AUTHORITY_UNBOUND', typed.shown(), unbound.detail)
    else:
        broken = label_rule(bound, typed, records)
        if broken is None:
            view['authority'] = {'shown': bound, 'bound': bound, 'code': None}
        else:
            view['authority'] = {'shown': UNKNOWN, 'bound': bound, 'code': broken[0], 'detail': broken[1]}
            decided = _decide(UNKNOWN, broken[0], typed.shown(), broken[1])
    view.update(decided)
    view['result'] = result_of(records)
    view['evidence'] = evidence_of(records)
    return view


def latest(views: list):
    """The latest of an attempt list by the store's own reservation order (the typed attempt's reservation event, whose
    id the store assigns monotonically), never by ordinal: ordinals restart per work item, design revision and stage."""
    ordered = sorted(views, key=lambda v: (v['reservedEventId'] is not None, v['reservedEventId'] or 0,
                                           v['operationKey']))
    return ordered[-1] if ordered else None


def project(outcome, *, project, backlog, store, conversations, read_artifact=None) -> dict:
    """The ``outcome-projection/v1`` of OUTCOME (``outcome:<uuid>``, text or ObjectiveRef), read-only."""
    root = L.parse(outcome) if isinstance(outcome, str) else outcome
    if not isinstance(root, L.ObjectiveRef):
        raise L.MalformedReference('REFERENCE_MALFORMED', f'the projection starts from an outcome: {root!r}')
    registry = R.build_registry(project=project, backlog=backlog, conversations=conversations)
    lineage = trace_mod.trace(root, trace_mod.Authorities(registry), project=project, backlog=backlog, store=store)
    executed = [(e['from'], e['to'], p.get('operation_key')) for e in lineage['edges']
                if e['relation'] == trace_mod.EXECUTED_BY for p in e['provenance']]
    attempts, store_read, why, epochs = {}, False, None, []
    if store is not None:
        try:
            with R.ReadOnlyIntegrationStore(store) as held:
                rows = held.attempts()
                by_key = {r.operation_key: r for r in rows}
                cache = {}

                def events_of(key):
                    if key not in cache:
                        cache[key] = held.events(key)
                    return cache[key]
                epochs = held.restore_epochs()
                for _task, _node, key in executed:
                    if key in by_key and key not in attempts:
                        typed = held.attempt_identity(key)
                        attempts[key] = attempt_view(by_key[key], rows, events_of,
                                                     identity=typed.identity if typed else None,
                                                     read_artifact=read_artifact, epochs=epochs)
                store_read = True
        except (store_mod.StoreError, sqlite3.Error, OSError) as exc:
            why = f'{type(exc).__name__}: {exc}'
    else:
        why = 'no integration store was given'
    nodes = {n['reference']: n for n in lineage['nodes']}
    tasks = []
    for node in sorted((n for n in lineage['nodes'] if n['role'] == 'work'), key=lambda n: n['reference']):
        keys = [key for task, _n, key in executed if task == node['reference'] and key in attempts]
        views = [attempts[k] for k in dict.fromkeys(keys)]
        last = latest(views)
        if last is not None:
            execution = {'status': last['executionStatus'], 'code': last['executionCode'],
                         'attempt': last['operationKey']}
        elif store_read and epochs:
            execution = {'status': UNKNOWN, 'code': 'NO_ATTEMPT' + UNPROVEN, 'attempt': None,
                         'restoreEpochs': [e['epochId'] for e in epochs],
                         'detail': 'no attempt is recorded, and a restore can lose a reservation'}
        elif store_read:
            execution = {'status': PENDING, 'code': 'NO_ATTEMPT', 'attempt': None}
        else:
            execution = {'status': UNKNOWN, 'code': 'STORE_UNAVAILABLE', 'attempt': None, 'detail': why}
        reached = [p.get('record') for e in lineage['edges'] if e['relation'] == trace_mod.FULFILLED_BY
                   and e['to'] == node['reference'] for p in e['provenance']]
        tasks.append({'reference': node['reference'], 'resolution': node['resolution']['outcome'],
                      'code': node['resolution']['code'],
                      'reachedThrough': 'attempt' if reached and all(r == trace_mod.STORE_RECORD for r in reached)
                      else 'listing',
                      'attempts': [v['operationKey'] for v in sorted(views, key=lambda v: v['reservedEventId'] or 0)],
                      'execution': execution})
    failures = [{'reference': n['reference'], 'role': n['role'], 'kind': n['kind'],
                 'outcome': n['resolution']['outcome'], 'code': n['resolution']['code'],
                 'detail': n['resolution']['detail']}
                for n in lineage['nodes'] if n['role'] in FAILURE_ROLES and n['resolution']['outcome'] != L.RESOLVED]
    # The lineage's own uncertainties, unfiltered: an attempt node is unresolved here by construction (its authority is
    # the Agent Server, which this process never asks: RESOLVER_NOT_CONFIGURED), and stays so. Every attempt node whose
    # attempt is bound to the fixture adds the fixture-authority uncertainty (R11: a projection that used a fixture is
    # never complete). U-06.1's item 8 is judged from the dispatcher-side trace in its run record (R6, PB-5).
    uncertainties = list(lineage['uncertainties'])
    for view in sorted(attempts.values(), key=lambda v: v['executionRef']):
        if view['authority'].get('bound') == FIXTURE:
            uncertainties.append({'reference': view['executionRef'], 'reason': 'fixture-authority',
                                  'code': FIXTURE_AUTHORITY,
                                  'detail': 'the attempt is bound to the fixture authority by its pinned route '
                                            'allowlist: no live authority was asked'})
    lineage_verdict = 'failed' if failures else 'incomplete' if uncertainties else 'complete'
    return {
        'format': FORMAT, 'outcome': root.text, 'lineageVerdict': lineage_verdict,
        'objective': nodes.get(root.text),
        'statements': [n for n in lineage['nodes'] if n['role'] == 'statement'],
        'designs': [n for n in lineage['nodes'] if n['role'] == 'design'],
        'tasks': tasks,
        'attempts': [attempts[k] for k in sorted(attempts)],
        'failures': failures,
        'lineageUncertainties': uncertainties,
        'coverage': dict(COVERAGE),
        'sources': {**lineage['sources'], 'integrationStore': 'read' if store_read else why,
                    'restoreEpochOpen': any(not e['closed'] for e in epochs), 'restoreEpochs': len(epochs)},
        'lineage': lineage,
    }


# ---------------------------------------------------------------------------- the Integration process's projection

STATUS = {'OUTCOME_INVALID': 400, 'PROJECTION_PROJECT_UNCONFIGURED': 503, 'PROJECTION_CONFIG_INVALID': 503,
          'PROJECTION_STORE_UNCONFIGURED': 503, 'PROJECTION_BACKLOG_UNAVAILABLE': 503}
REMEDIES = {
    'OUTCOME_INVALID': 'name the outcome by its id: GET /outcomes/<uuid> (the id of outcome:<uuid>)',
    'PROJECTION_PROJECT_UNCONFIGURED': 'set components.owner_host (project_repository, project_repository_id, '
                                       'backlog_command) in config.yml and restart the Integration process',
    'PROJECTION_CONFIG_INVALID': 'correct components.owner_host as example_config.yml describes it, then restart',
    'PROJECTION_STORE_UNCONFIGURED': 'start the Integration process through service.py up, which names the '
                                     'integration store',
    'PROJECTION_BACKLOG_UNAVAILABLE': 'make components.owner_host.backlog_command name the pinned Backlog.md '
                                      '(on PATH, or its cli.js with node on PATH), then restart',
}


class ProjectionRefused(Exception):
    """A refusal with a stable code; nothing is read beyond the configuration."""

    def __init__(self, code: str, detail: str):
        self.code, self.detail, self.status, self.remedy = code, detail, STATUS[code], REMEDIES[code]
        super().__init__(f'{code}: {detail}')


class Projection:
    """The projection of the Integration process: its project configuration (RAW, ``components.owner_host``), the
    integration store's path and the Owner conversation store's path (both opened read-only per request)."""

    def __init__(self, raw_config, integration_store_path, conversations_path, *,
                 read_artifact: Callable[[str], bytes] | None = None):
        self.raw, self.read_artifact = raw_config, read_artifact
        self.store = None if integration_store_path is None else Path(integration_store_path)
        self.conversations = None if conversations_path is None else Path(conversations_path)

    def project(self, outcome_id) -> dict:
        try:
            root = L.parse(f'outcome:{outcome_id}') if isinstance(outcome_id, str) else None
        except L.MalformedReference:
            root = None
        if not isinstance(root, L.ObjectiveRef) or root.revision is not None:
            raise ProjectionRefused('OUTCOME_INVALID', 'the path does not name an outcome id')
        try:
            config = capture.project_config(self.raw)
        except capture.CaptureRefused as exc:
            code = ('PROJECTION_PROJECT_UNCONFIGURED' if exc.code == 'CAPTURE_PROJECT_UNCONFIGURED'
                    else 'PROJECTION_CONFIG_INVALID')
            raise ProjectionRefused(code, exc.detail) from None
        if self.store is None:
            raise ProjectionRefused('PROJECTION_STORE_UNCONFIGURED', 'no integration store was given')
        try:
            backlog = planning.tool_argv(config.backlog_command)
        except planning.CannotRun as exc:
            raise ProjectionRefused('PROJECTION_BACKLOG_UNAVAILABLE', str(exc)) from None
        return project(root, project=config.project_repository, backlog=backlog, store=self.store,
                       conversations=self.conversations, read_artifact=self.read_artifact)
