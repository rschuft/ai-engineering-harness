"""The model-selection recorder (plan leaf S-03.5, slice 2; decision 0018 point 3): the act by which the
engineering manager records the exact model identifiers selected inside the model-access envelope the Owner
authorized.

A selection is a ``delegated-decision/v1`` record (``delegated_decision.py``) of kind ``select-models``:
decided by ``agent:engineering-manager`` only (the table's row; the product manager is refused
``DECIDER_NOT_DELEGATED``) under ``decision:0018`` point ``3``, resting on an ``envelope-receipt`` basis
``{type, receipt}`` that names the provider envelope's authorization (a confirmed ``provider-envelope`` receipt
of the authorization recorder, ``owner-authorization/v1/<nonce>``). Its subject: ``leaf`` (the plan leaf that
makes the paid call), ``models`` (``{<family>: [{id, use, cost}]}``), ``verified`` (``{source, at}``: where
current provider information was read) and ``supersedes`` (the selection it replaces, set by the recorder: the
last confirmed one, or null).

``delegate`` checks, in this order, and refuses with a stable code (``REMEDIES``) leaving nothing reserved:
the row, the decider and the basis's shape; decision 0018 at the harness repository's ``HEAD``, with ``Status:
Accepted (Owner) -``; the basis receipt in the integration store (no store: ``AUTHORITY_UNAVAILABLE``; absent:
``DELEGATION_BASIS_NOT_RECORDED``; not the recorder's, of another kind or not confirmed:
``DELEGATION_BASIS_NOT_AUTHORITY``); that receipt being the governing, unexpired provider-envelope authorization
(superseded, unsettled after, or expired: ``DELEGATION_BASIS_NOT_AUTHORITY``); the subject
(``SELECTION_INVALID``). It then writes a write-ahead receipt at the next position of the one series
``model-selection/v1/<sequence>`` (format ``aieh-model-selection/1``, actor ``selection-recorder/1``; a position
taken meanwhile: ``SELECTION_POSITION_TAKEN``), a copy of the record under
``<state>/delegated-decisions/model-selections/``, and confirms the receipt (a write that stopped after the
reservation: the receipt is failed and its position spent, ``SELECTION_WRITE_FAILED``).

**Checked at the act:** the row, the decider, the basis's shape, decision 0018 at ``HEAD``, the basis receipt
and that it governs, the subject's shape. **Not checked** (decision 0020 point 7's form): who ran the command;
that the identifiers were verified against current provider information; that the expected costs are right;
that the record was presented to the Owner before the first paid operation (S-03.3's proof, not this act's).

The module imports no Gitea and no credential module and reads no credential; ``delegate`` reads the harness
repository through the repository-access module (Dulwich, from the Python tools set). Whether the broker starts
on a selection is the broker's check at its start.

Usage (from the repository root, under the tools interpreter):

    <tools python> -I -B integrations/owner/selection_recorder.py delegate --selection FILE \\
        --decided-by agent:engineering-manager --basis FILE
    <tools python> -I -B integrations/owner/selection_recorder.py status

Exit status: 0 done (JSON on standard output), 2 refused (the code and its remedy on standard error; nothing
recorded), 1 failed (the receipt is failed and its position spent).
"""
from __future__ import annotations

import argparse
import contextlib
import datetime
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Callable, NamedTuple

HERE = Path(os.path.realpath(__file__)).parent
REPO = HERE.parents[1]


def _load(name, path):
    if (module := sys.modules.get(name)) is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = sys.modules[name] = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except BaseException:
            del sys.modules[name]
            raise
    return module


D = _load('owner_decision', HERE / 'owner_decision.py')
G = _load('delegated_decision', HERE / 'delegated_decision.py')
ED = _load('envelope_decisions', HERE / 'envelope_decisions.py')
store_module = _load('integration_store', REPO / 'integrations' / 'store' / 'integration_store.py')
paths = _load('aieh_paths', REPO / 'integrations' / 'paths' / 'aieh_paths.py')

KIND = 'select-models'
RECORDER = ED.SELECTION_RECORDER
DELEGATED_STATE = ('delegated-decisions', 'model-selections')   # never under owner-authorization/
SELECTION_INPUT = ('leaf', 'models', 'verified')               # the file's fields; the recorder adds supersedes
MAX_FILE_BYTES = 64 * 1024

REMEDIES = {
    # the delegation codes, as delegated_decision.py raises them
    'DELEGATION_KIND_UNKNOWN': 'no accepted record delegates this kind: the decision is the Owner\'s',
    'DECIDER_NOT_DELEGATED': 'decision 0018 point 3 delegates technical model selection to agent:engineering-manager '
                             'only; the product manager never selects the models',
    'DELEGATION_BASIS_INVALID': 'give the basis as {"type": "envelope-receipt", "receipt": '
                                '"owner-authorization/v1/<nonce>"}, the provider envelope\'s authorization',
    'DELEGATION_NOT_ACCEPTED': 'decision 0018 is not Accepted (Owner) at the harness repository\'s HEAD: the model '
                               'selection is the Owner\'s, in the envelope itself (selection: envelope)',
    'AUTHORITY_UNAVAILABLE': 'run from a full clone under the tools interpreter, with the integration store',
    'DELEGATION_BASIS_NOT_RECORDED': 'name a receipt the integration store holds: the confirmed provider-envelope '
                                     'authorization (authorization_recorder.py status shows none; the broker\'s '
                                     'envelope command shows the live envelope)',
    'DELEGATION_BASIS_NOT_AUTHORITY': 'name the governing, unexpired provider-envelope authorization: the last '
                                      'confirmed one, with no later one unsettled (resolve it first); a superseded or '
                                      'expired envelope is not an authority',
    # the selection recorder's own
    'SELECTION_INVALID': 'give the selection as {leaf, models: {<family>: [{id, use, cost}]}, verified: {source, '
                         'at}}: exact identifiers (no wildcard, no duplicate), one-line texts, a UTC time',
    'SELECTION_POSITION_TAKEN': 'another selection took the position meanwhile: read status, then delegate again',
    'SELECTION_WRITE_FAILED': 'the record could not be written after its receipt was reserved: the receipt is failed '
                              'and its position spent; repair the cause (the detail says what) and delegate again',
}


class RecorderError(Exception):
    """A refusal (nothing recorded; exit 2) or a failure after the reservation (exit 1), with a stable code."""

    def __init__(self, code, detail, *, refusal=True, **details):
        self.code, self.detail, self.remedy, self.refusal, self.details = code, detail, REMEDIES[code], refusal, details
        super().__init__(f'{code}: {detail}. Remedy: {self.remedy}.')


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


def timestamp(moment):
    return moment.astimezone(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


class Context(NamedTuple):
    """Where the act writes and what it reads: STATE_ROOT the managed ``state`` category (the record copies go
    under ``delegated-decisions/model-selections/``), STORE the integration store (None: the basis cannot be
    read, AUTHORITY_UNAVAILABLE), HARNESS the harness repository whose ``HEAD`` holds decision 0018. A test passes
    its own; only main() builds the managed context."""
    state_root: Path
    store: object
    harness: Path
    now: Callable = utc_now


def _check_context(ctx):
    if not isinstance(ctx, Context) or ctx.state_root is None or ctx.harness is None:
        raise ValueError('a context needs its own state root and the harness repository')


@contextlib.contextmanager
def managed_context():
    """The command line's context: the managed ``state`` category, the integration store at its managed
    location (the file the other recorders use), and this checkout as the harness repository. It opens no Gitea
    and reads no credential."""
    res = paths.resolve()
    state = paths.ensure('state', res)
    with store_module.open_store(paths.ensure('state', res, 'integration') / 'integration.sqlite') as store:
        yield Context(state, store, REPO)


def _receipt_report(store, key):
    reservation = store.get(key)
    return {'operation_key': key, 'format': ED.SELECTION_FORMAT, 'state': reservation.state,
            'events': [event.to_state for event in store.events(key)]}


def _head(store):
    series = ED.selections(store)
    return series, ED.last_confirmed_selection(series)


def _subject(selection, head):
    if not isinstance(selection, dict) or list(selection) != list(SELECTION_INPUT):
        raise RecorderError('SELECTION_INVALID', f'the selection must have exactly {", ".join(SELECTION_INPUT)}')
    previous = None
    if head is not None:
        decision = (head.intent or {}).get('decision')
        previous = decision.get('decisionId') if isinstance(decision, dict) else None
        if not isinstance(previous, str) or not D.UUID4.match(previous):
            raise ValueError(f'the integration store\'s receipt {head.key} is malformed')
    subject = {**selection, 'supersedes': previous}
    problems = G.selection_subject_problems(subject)
    if problems:
        raise RecorderError('SELECTION_INVALID', '; '.join(problems))
    return subject


def delegate(ctx, selection, *, decided_by, basis, new_decision_id=None):
    """Record the model selection SELECTION ({leaf, models, verified}) that DECIDED_BY makes under decision 0018
    point 3, resting on BASIS (the provider envelope's receipt)."""
    _check_context(ctx)
    failure = None
    try:
        authority = G.read_authority(ctx.harness, KIND, decided_by, basis, store=ctx.store)
    except G.DelegationRefused as exc:
        failure = exc
    if failure is not None:
        raise RecorderError(failure.code, failure.detail)
    now = ctx.now()
    problem = ED.basis_problem(ctx.store, basis['receipt'], now)
    if problem is not None:
        raise RecorderError('DELEGATION_BASIS_NOT_AUTHORITY', problem)
    series, head = _head(ctx.store)
    subject = _subject(selection, head)
    decision = G.decide(authority, subject, recorded_at=timestamp(now),
                        decision_id=None if new_decision_id is None else str(new_decision_id()))
    position = len(series) + 1
    key = ED.selection_key(position)
    intent = {'format': ED.SELECTION_FORMAT, 'recorder': RECORDER, 'series': 'selection', 'decision': decision,
              'sequence': position, 'receipt': basis['receipt']}
    taken = None
    try:
        reserved = ctx.store.reserve(key, intent, actor=RECORDER)
    except store_module.ConflictingReservation as exc:
        taken = str(exc)
    else:
        if not reserved.created:
            taken = f'{key} already exists'
    if taken is not None:
        raise RecorderError('SELECTION_POSITION_TAKEN', taken)
    try:
        path = Path(ctx.state_root).joinpath(*DELEGATED_STATE, f'{decision["decisionId"]}.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'x', encoding='utf-8', newline='\n') as handle:
            handle.write(G.dumps(decision))
        ctx.store.transition(key, 'dispatched', actor=RECORDER, reason='the selection is recorded',
                             detail={'recordedAt': decision['recordedAt']}, expected_from='reserved')
        ctx.store.transition(key, 'confirmed', actor=RECORDER, reason='the model selection is recorded',
                             detail={'decisionId': decision['decisionId']}, expected_from='dispatched')
    except Exception as exc:  # noqa: BLE001 - whatever stopped the act, its position is spent: mark it failed
        with contextlib.suppress(Exception):
            current = ctx.store.get(key)
            if current is not None and current.state in ('reserved', 'dispatched'):
                ctx.store.transition(key, 'failed', actor=RECORDER, reason='the act stopped before it was confirmed',
                                     detail={'code': 'SELECTION_WRITE_FAILED', 'error': type(exc).__name__},
                                     expected_from=current.state)
        if isinstance(exc, OSError):
            raise RecorderError('SELECTION_WRITE_FAILED', f'{type(exc).__name__} after {key} was reserved; the '
                                f'receipt is {ctx.store.get(key).state} and its position spent', refusal=False,
                                receipt=key) from None
        raise
    return {'decision': decision, 'receipt': _receipt_report(ctx.store, key),
            'authority': {'authority': 'delegated', 'record': authority.row.record, 'point': authority.row.point,
                          'revision': authority.revision, 'decidedBy': decision['decidedBy'],
                          'basis': decision['delegation']['basis']}}


def status(ctx):
    """The series' head (its decision, basis receipt, leaf and identifiers), its next position, its failed and
    unsettled positions, and the governing provider-envelope authorization. Reads only."""
    _check_context(ctx)
    if ctx.store is None:
        raise RecorderError('AUTHORITY_UNAVAILABLE', 'no integration store was given')
    series, head = _head(ctx.store)
    view = None
    if head is not None:
        decision = (head.intent or {}).get('decision') or {}
        subject = decision.get('subject') or {}
        view = {'sequence': head.position, 'receipt': head.key, 'decisionId': decision.get('decisionId'),
                'basis': (head.intent or {}).get('receipt'), 'leaf': subject.get('leaf'),
                'models': {family: [entry.get('id') for entry in entries if isinstance(entry, dict)]
                           for family, entries in (subject.get('models') or {}).items() if isinstance(entries, list)}}
    envelope = ED.governing(ctx.store)
    return {'head': view, 'next': len(series) + 1, 'failed': [s.position for s in series if s.state == 'failed'],
            'unsettled': [{'sequence': s.position, 'state': s.state} for s in series
                          if s.state not in ('confirmed', 'failed')],
            'envelope': {'receipt': envelope.candidate.key} if envelope.code is None
            else {'code': envelope.code, 'detail': envelope.detail}}


# ---------------------------------------------------------------------------- command line


def _read_json(path, code):
    try:
        data = Path(path).read_bytes()
        if len(data) > MAX_FILE_BYTES:
            raise ValueError('too large')
        return json.loads(data.decode('utf-8'))
    except (OSError, ValueError) as exc:
        raise RecorderError(code, f'{path}: {type(exc).__name__}') from None


def parser():
    top = argparse.ArgumentParser(prog='selection_recorder.py', description='Record the technical model selection '
                                  'delegated by decision 0018 point 3 (plan leaf S-03.5). Exit 0 done, 2 refused, 1 '
                                  'failed.')
    commands = top.add_subparsers(dest='command', required=True)
    d = commands.add_parser('delegate', help='record a model selection resting on the provider envelope\'s receipt')
    d.add_argument('--selection', required=True, help='{leaf, models, verified} as JSON')
    d.add_argument('--decided-by', required=True, help='agent:engineering-manager')
    d.add_argument('--basis', required=True, help='{"type": "envelope-receipt", "receipt": ...} as JSON')
    commands.add_parser('status', help='the series\' head and the governing envelope; reads only')
    return top


def main(argv=None, out=None, err=None, context=None):
    """The command line. CONTEXT (a context manager factory taking nothing) stands in for managed_context in
    tests."""
    args = parser().parse_args(argv)
    out, err = out or sys.stdout, err or sys.stderr
    if out is sys.stdout and hasattr(out, 'reconfigure'):
        out.reconfigure(encoding='utf-8')
    try:
        with (context or managed_context)() as ctx:
            if args.command == 'status':
                result = status(ctx)
            else:
                result = delegate(ctx, _read_json(args.selection, 'SELECTION_INVALID'), decided_by=args.decided_by,
                                  basis=_read_json(args.basis, 'DELEGATION_BASIS_INVALID'))
    except RecorderError as exc:
        err.write(f'selection-recorder: {exc}\n')
        return 2 if exc.refusal else 1
    except (ValueError, paths.PathsError, store_module.StoreError) as exc:
        err.write(f'selection-recorder: {exc}\n')
        return 2
    out.write(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
