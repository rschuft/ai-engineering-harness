"""Recovering after a dispatcher restart (plan leaf E-01.4.2, slice 5b; the architect's rulings R16 and R18 to R21;
draft decision 0027 points 4 to 7).

``recover(store, transport=, actor=, read_artifact=)`` is the restart procedure, run by a dispatcher composition root
before its first act. It keeps two questions apart (R16): whether the act that wrote a row will still record its
outcome, which only the dispatcher lock answers (``dispatcher_lock.py``: a holder that finds a typed attempt
``reserved`` or ``dispatched``, or a turn journal ``dispatched``, knows its act has ended), and what happened at the
Agent Server, which only the Agent Server answers (E-01.4.1's lookup for a create, decision 0024 point 6.1's event read
for a message). It never infers the second from the first, nor from the store alone (decision 0004 point 7).

Holding the lock throughout (DISPATCHER_BUSY, nothing read or changed, when another act holds it), it settles exactly
this table (R18), and nothing else:

=======================================  ==========================  =================================================
Found                                    What is read                Then
=======================================  ==========================  =================================================
typed attempt ``reserved``               ``GET /api/conversations/   ``404``: ``failed`` (``NOT_SENT``). ``200`` with
                                         {reserved id}`` on its      that id: no change, held
                                         pinned allowlist            (``RESERVED_CONVERSATION_FOUND``). Anything else:
                                                                     no change, held, asked again at the next recover
typed attempt ``dispatched``             nothing yet                 ``unknown`` (``OUTCOME_UNKNOWN``), then as the
                                                                     next row
typed attempt ``unknown``                E-01.4.1's lookup,          ``200``: ``confirmed`` (reattached); ``404``:
                                         unchanged (``reconcile``)   ``failed``; anything else: stays ``unknown``, held
turn journal ``dispatched``              nothing yet                 ``unknown`` (``OUTCOME_UNKNOWN``), then as the
                                                                     next row
turn journal ``unknown``, its attempt    the conversation's events   the message is there: ``confirmed``
``confirmed`` with no end record         (``reconcile_turn``,        (``reconciled-from-events``); not there, or not
                                         unchanged)                  readable: stays ``unknown``, held
turn journal ``reserved``                nothing                     no change; held, not sent (R21)
any other key                            nothing                     not read, not asked, not changed
=======================================  ==========================  =================================================

Inside a restore epoch the store's own sweep runs first, unchanged (``IntegrationStore.reconcile`` moves every
``dispatched`` row to ``unknown``), in place of the two ``dispatched`` rows above; recover then adds the turn arm, so
that the turn journals the sweep made ``unknown`` are reconciled and the epoch can close.

**What it never does** (R19): it sends no create and no message, ends no attempt, reserves nothing, deletes nothing
and calls no broker. Every call goes through ``_ReadOnly``, which refuses any method but ``GET`` before the transport
(the caller then sees no answer: never a settlement). A client that cannot be built, or a call the client refuses, is
indeterminate. A row that another writer moved between recover's read and its transition (the store's
``IllegalTransition``) is reported in ``conflicts`` and left as it now is; the transition is never retried.

**Holds** (R21): where the effect cannot be observed or repeated, the attempt is held on its conversation, never
resumed. Each held row is reported with its code and the act that resolves it. An attempt with a broker grant journal
is reported with that journal's state and ``end_attempt`` as its resolver; recover never touches it.

The report (``recovery-report/v1``, in memory, as E-01.4.1's observations are): ``entries`` (for each typed attempt
and turn journal found unsettled: its class, the state found, the basis, the verdict, the HTTP status of a lookup and
the state left), ``held``, ``grants``, ``conflicts`` and ``creates`` (the store reconcile's outcome for the typed
attempts it asked about). The durable trace is the transitions' reasons and details. A second recover changes nothing
settled and asks only about what is still unsettled. Standard library only.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


di = _load('dispatch_inputs', HERE / 'dispatch_inputs.py')
RC = _load('aieh_dispatch_reconcile', HERE / 'reconcile.py')
AR = _load('attempt_run', HERE / 'attempt_run.py')
AE = di._attempt_end()
store = di.store
DispatchRefused = di.DispatchRefused

REPORT_FORMAT = 'ai-engineering-harness/dispatch/recovery-report/v1'
ATTEMPT, TURN = 'typed-attempt', 'turn-journal'
TURN_KEY_RE = re.compile(r'dispatch/attempt/(' + AR.ATTEMPT_ID_RE.pattern + r')/turn')

# The transitions' codes (the Owner recorders' vocabulary) and reasons.
NOT_SENT, OUTCOME_UNKNOWN = 'NOT_SENT', 'OUTCOME_UNKNOWN'
REASON_NOT_SENT = 'recovered: the create was never sent (its reserved conversation is not found)'
REASON_CREATE_UNKNOWN = 'recovered: the create\'s outcome was never recorded'
REASON_TURN_UNKNOWN = 'recovered: the message\'s outcome was never recorded'
LOCK_BASIS = 'dispatcher-lock'      # what moved a dispatched row: the lock's evidence, no call

# The held rows' codes, and the act that resolves each.
RESERVED_CONVERSATION_FOUND = 'RESERVED_CONVERSATION_FOUND'
LOOKUP_INDETERMINATE = 'LOOKUP_INDETERMINATE'
TURN_NOT_SENT = 'TURN_NOT_SENT'
TURN_UNRECONCILED = 'TURN_UNRECONCILED'
RESOLVERS = {
    RESERVED_CONVERSATION_FOUND: 'none designed: the engineering manager (a reserved attempt whose conversation '
                                 'exists can arise only after a restore; decision 0004 point 7)',
    LOOKUP_INDETERMINATE: 'recover, which asks again',
    OUTCOME_UNKNOWN: 'recover, which asks again (E-01.4.1\'s lookup)',
    TURN_NOT_SENT: 'end_interrupted_attempt (trigger attempt-stopped), then a new attempt',
    TURN_UNRECONCILED: 'recover, which reads the events again; or end_interrupted_attempt (trigger attempt-stopped)',
}
GRANT_RESOLVER = 'end_attempt'
ATTEMPT_NOT_RUNNABLE = 'attempt-not-confirmed-or-ended'   # a turn's attempt not confirmed, or with an end record


class ReadOnlyRefused(Exception):
    """recover asked its transport for something other than a GET: refused before the transport (never sent)."""


class _ReadOnly:
    """The caller's transport, for GETs only (R19). Anything else is refused before the transport is called."""

    def __init__(self, transport):
        self.transport = transport

    def __call__(self, method, path, body=None, **kwargs):
        if method != 'GET' or body is not None or kwargs:
            raise ReadOnlyRefused(f'recover makes GETs only: {method} {path} refused')
        return self.transport(method, path, body)


def _typed(integration_store, key: str) -> bool:
    return RC.in_namespace(key) and integration_store.attempt_identity(key) is not None


def turn_attempt(integration_store, reservation) -> str | None:
    """The operation key of the typed attempt whose turn journal RESERVATION is, or None when it is not one: its key
    is ``dispatch/attempt/<attempt id>/turn``, its intent an ``attempt-turn/v1`` naming a typed attempt of that id."""
    match = TURN_KEY_RE.fullmatch(reservation.operation_key)
    if match is None:
        return None
    try:
        intent = json.loads(reservation.intent_json)
    except ValueError:
        return None
    if not isinstance(intent, dict):
        return None
    operation_key = intent.get('operationKey')
    if intent.get('format') != AR.TURN_FORMAT or not isinstance(operation_key, str) \
            or not _typed(integration_store, operation_key) or store.attempt_id_for(operation_key) != match.group(1):
        return None
    return operation_key


def _lookup_reserved(integration_store, reservation, transport, read_artifact) -> tuple[str, dict]:
    """E-01.4.1's lookup for a ``reserved`` typed attempt: the record read with ``stored_inputs(state='reserved')``,
    the reserved conversation looked up through the client on its pinned allowlist; the verdict and its basis."""
    key = reservation.operation_key
    try:
        resolved = di.stored_inputs(integration_store, key, state='reserved')
    except DispatchRefused as refusal:
        return RC.INDETERMINATE, {'basis': RC.RECORD_UNREADABLE, 'code': refusal.code}
    conversation_id = reservation.conversation_id
    if conversation_id != store.conversation_id_for(key):
        return RC.INDETERMINATE, {'basis': RC.CONVERSATION_NOT_RESERVED}
    try:
        client = AE._client(resolved, transport)(read_artifact)
    except DispatchRefused as refusal:
        return RC.INDETERMINATE, {'basis': RC.CLIENT_UNAVAILABLE, 'code': refusal.code}
    except Exception as exc:  # noqa: BLE001 - a client that cannot be built settles nothing
        return RC.INDETERMINATE, {'basis': RC.CLIENT_UNAVAILABLE, 'error': type(exc).__name__}
    try:
        answer = client.call('GET', RC.CONVERSATION_ROUTE, params={'conversation_id': conversation_id})
    except DispatchRefused as refusal:
        return RC.INDETERMINATE, {'basis': RC.CALL_REFUSED, 'code': refusal.code}
    except Exception as exc:  # noqa: BLE001 - no answer: nothing is inferred from it
        return RC.INDETERMINATE, {'basis': RC.NO_ANSWER, 'error': type(exc).__name__}
    status = answer.get('status') if isinstance(answer, dict) else None
    return RC.verdict_of(answer, conversation_id), {'basis': RC.LOOKUP, 'conversationId': conversation_id,
                                                    'httpStatus': status if type(status) is int else None}


class _Recovery:
    def __init__(self, integration_store, transport, actor, read_artifact):
        self.store, self.reads, self.actor, self.read_artifact = (integration_store, _ReadOnly(transport), actor,
                                                                  read_artifact)
        self.entries, self.held, self.conflicts = {}, [], []

    def entry(self, reservation, kind):
        return self.entries.setdefault(reservation.operation_key, {
            'operationKey': reservation.operation_key, 'class': kind, 'found': reservation.state, 'basis': None,
            'verdict': None, 'httpStatus': None})

    def hold(self, key, kind, code, **extra):
        self.held.append({'operationKey': key, 'class': kind, 'code': code, 'resolver': RESOLVERS[code], **extra})

    def move(self, key, from_state, to_state, reason, detail) -> bool:
        """One transition, expected from FROM_STATE; another writer's move is a conflict, reported, never retried."""
        try:
            di._mark(self.store, key, from_state, to_state, self.actor, reason, detail)
            return True
        except store.IllegalTransition as exc:
            held = self.store.get(key)
            self.conflicts.append({'operationKey': key, 'expected': from_state, 'to': to_state,
                                   'found': getattr(held, 'state', None), 'error': type(exc).__name__})
            return False

    # -- the rows ----------------------------------------------------------------------------------------------
    def outcome_unknown(self, reservation, kind):
        """A ``dispatched`` typed attempt or turn journal: the lock establishes that its act ended unrecorded."""
        entry = self.entry(reservation, kind)
        entry.update(basis=LOCK_BASIS, verdict='outcome-unknown')
        self.move(reservation.operation_key, 'dispatched', 'unknown',
                  REASON_CREATE_UNKNOWN if kind == ATTEMPT else REASON_TURN_UNKNOWN,
                  {'code': OUTCOME_UNKNOWN, 'answer': 'not recorded', 'basis': LOCK_BASIS})

    def reserved_attempt(self, reservation):
        entry = self.entry(reservation, ATTEMPT)
        verdict, observed = _lookup_reserved(self.store, reservation, self.reads, self.read_artifact)
        entry.update(verdict=verdict, **observed)
        key = reservation.operation_key
        if verdict == RC.NOT_PERFORMED:
            self.move(key, 'reserved', 'failed', REASON_NOT_SENT, {'code': NOT_SENT, **observed})
        elif verdict == RC.PERFORMED:
            self.hold(key, ATTEMPT, RESERVED_CONVERSATION_FOUND, conversationId=reservation.conversation_id)
        else:
            self.hold(key, ATTEMPT, LOOKUP_INDETERMINATE, basis=observed['basis'])

    def unknown_attempts(self) -> dict:
        """E-01.4.1's reconciliation, unchanged: ``IntegrationStore.reconcile`` with ``create_oracle`` (inside an
        epoch, its sweep first). A transition another writer pre-empted is a conflict; the reconcile is then run
        again for the rows still unsettled, each asked at most once (the oracle's verdict is kept per key)."""
        observations, asked, last = [], {}, [None]
        oracle = RC.create_oracle(self.store, transport=self.reads, read_artifact=self.read_artifact,
                                  observations=observations)

        def once(reservation):
            key = reservation.operation_key
            if key not in asked:
                asked[key] = oracle(reservation)
            last[0] = key
            return asked[key]
        for _ in range(len(self.store.attempts()) + 1):
            last[0] = None
            try:
                self.store.reconcile(once, actor=self.actor)
                break
            except store.IllegalTransition as exc:
                key = last[0]
                held = self.store.get(key) if key else None
                self.conflicts.append({'operationKey': key, 'expected': 'unknown' if key else 'dispatched',
                                       'found': getattr(held, 'state', None), 'error': type(exc).__name__})
        typed = {k: v for k, v in asked.items() if _typed(self.store, k)}
        states = {k: self.store.get(k).state for k in typed}
        for observation in observations:
            key = observation['operationKey']
            if key in typed:
                entry = self.entry(self.store.get(key), ATTEMPT)
                entry.update(verdict=observation['verdict'], basis=observation.get('basis'),
                             httpStatus=observation.get('httpStatus'))
                if states[key] == 'unknown':
                    self.hold(key, ATTEMPT, OUTCOME_UNKNOWN, basis=observation.get('basis'))
        return {'confirmed': sorted(k for k, s in states.items() if s == 'confirmed' and typed[k] == RC.PERFORMED),
                'failed': sorted(k for k, s in states.items() if s == 'failed' and typed[k] == RC.NOT_PERFORMED),
                'still_unknown': sorted(k for k, s in states.items() if s == 'unknown'),
                'observations': [o for o in observations if o['operationKey'] in typed]}

    def unknown_turn(self, reservation, operation_key):
        entry = self.entry(reservation, TURN)
        key = reservation.operation_key
        attempt = self.store.get(operation_key)
        if attempt is None or attempt.state != 'confirmed' \
                or AE.end_record(self.store, store.attempt_id_for(operation_key)) is not None:
            entry.update(basis=ATTEMPT_NOT_RUNNABLE, verdict='not-asked')
            self.hold(key, TURN, TURN_UNRECONCILED, basis=ATTEMPT_NOT_RUNNABLE)
            return
        try:
            resolved = di.stored_inputs(self.store, operation_key, state='confirmed')
            client = AE._client(resolved, self.reads)(self.read_artifact)
        except DispatchRefused as refusal:
            entry.update(basis=RC.CLIENT_UNAVAILABLE, verdict=RC.INDETERMINATE, code=refusal.code)
            self.hold(key, TURN, TURN_UNRECONCILED, basis=RC.CLIENT_UNAVAILABLE)
            return
        except Exception as exc:  # noqa: BLE001 - a client that cannot be built settles nothing
            entry.update(basis=RC.CLIENT_UNAVAILABLE, verdict=RC.INDETERMINATE, error=type(exc).__name__)
            self.hold(key, TURN, TURN_UNRECONCILED, basis=RC.CLIENT_UNAVAILABLE)
            return
        try:
            AR.reconcile_turn(self.store, operation_key, client, actor=self.actor)
        except store.IllegalTransition as exc:
            held = self.store.get(key)
            self.conflicts.append({'operationKey': key, 'expected': 'unknown', 'to': 'confirmed',
                                   'found': getattr(held, 'state', None), 'error': type(exc).__name__})
            return
        except DispatchRefused as refusal:
            if refusal.code == 'TURN_ALREADY_SENT':     # another writer settled it after it was read
                held = self.store.get(key)
                self.conflicts.append({'operationKey': key, 'expected': 'unknown', 'to': 'confirmed',
                                       'found': getattr(held, 'state', None), 'error': refusal.code})
                return
            entry.update(basis='events', verdict=RC.INDETERMINATE, code=refusal.code)
            self.hold(key, TURN, TURN_UNRECONCILED, basis='events', refusal=refusal.code)
            return
        entry.update(basis='events', verdict=RC.PERFORMED)

    def grants(self) -> list:
        out = []
        for key, entry in self.entries.items():
            if entry['class'] != ATTEMPT:
                continue
            attempt_id = store.attempt_id_for(key)
            journal = di.GRANT_JOURNAL_KEY.format(attempt_id=attempt_id)
            held = self.store.get(journal)
            if held is not None:
                out.append({'attemptId': attempt_id, 'operationKey': key, 'journal': journal, 'state': held.state,
                            'resolver': GRANT_RESOLVER})
        return out

    def run(self) -> dict:
        epoch = bool(self.store.open_epochs())
        found = self.store.attempts(['reserved', 'dispatched', 'unknown'])
        attempts = [r for r in found if _typed(self.store, r.operation_key)]
        turns = [(r, op) for r in found if (op := turn_attempt(self.store, r)) is not None]
        for reservation in attempts:
            self.entry(reservation, ATTEMPT)
        for reservation, _ in turns:
            self.entry(reservation, TURN)
        if not epoch:   # inside an epoch the store's sweep moves every dispatched row (unknown_attempts)
            for reservation in attempts:
                if reservation.state == 'dispatched':
                    self.outcome_unknown(reservation, ATTEMPT)
            for reservation, _ in turns:
                if reservation.state == 'dispatched':
                    self.outcome_unknown(reservation, TURN)
        for reservation in attempts:
            if reservation.state == 'reserved':
                self.reserved_attempt(reservation)
        creates = self.unknown_attempts()
        for reservation, operation_key in turns:
            now = self.store.get(reservation.operation_key)
            if now.state == 'reserved':
                self.entry(reservation, TURN).update(basis=None, verdict='not-sent')
                self.hold(reservation.operation_key, TURN, TURN_NOT_SENT)
            elif now.state == 'unknown':
                self.unknown_turn(now, operation_key)
        for key, entry in self.entries.items():
            entry['state'] = self.store.get(key).state
        return {'format': REPORT_FORMAT, 'epoch': epoch, 'entries': list(self.entries.values()), 'held': self.held,
                'grants': self.grants(), 'conflicts': self.conflicts, 'creates': creates}


def recover(integration_store, *, transport: Callable[[str, str, dict | None], object], actor: str,
            read_artifact: Callable[[str], bytes] = di.read_profile_artifact) -> dict:
    """The restart procedure (the module docstring's table), under the dispatcher lock: DISPATCHER_BUSY (or
    DISPATCHER_LOCK_UNAVAILABLE) before anything is read or changed when it cannot be taken. Returns the report."""
    if not callable(transport):
        raise TypeError('transport must be callable as transport(method, path, body)')
    with di.dispatcher_lock(integration_store):
        return _Recovery(integration_store, transport, actor, read_artifact).run()
