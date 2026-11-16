"""Reconcile a create whose acknowledgement was lost (plan leaf E-01.4.1, blueprint #execution-qualification).

``dispatch_inputs.dispatch`` sends one create per attempt, under the attempt's reserved conversation id, and never
retries it. When the create was sent and its outcome is not known (no answer, a 5xx, another 2xx, or a 2xx that is
not the reserved conversation) the attempt is ``unknown``; a restore epoch makes every ``dispatched`` attempt
``unknown`` too (``IntegrationStore.reconcile``). An ``unknown`` attempt is a live claim (``reserve_attempt``:
LiveClaim), so no other attempt on its work item, design revision and stage is reserved, and no create is sent,
until it is reconciled here. Nothing here sends a create: the lookup is the attempt's one way out of ``unknown``.

``reconcile_creates(store, transport=, actor=, read_artifact=)`` runs ``IntegrationStore.reconcile`` with
``create_oracle``, the store's oracle for the attempts of the typed attempt namespace (``attempt/v1/``, the operation
keys ``reserve_attempt`` writes; the architect's I1 design, slice 3):

======================================================  =================  ==========================================
What the oracle finds                                   Verdict            The store then (its reconcile contract)
======================================================  =================  ==========================================
a key outside ``attempt/v1/`` (a recorder's receipt,    ``indeterminate``  the receipt stays ``unknown``; its own
a dispatch journal, any other key): no call is made                        resolver settles it
a typed attempt whose stored record is not its          ``indeterminate``  stays ``unknown``
dispatch record, or whose pinned route allowlist
cannot be read: no call is made
``GET /api/conversations/{reserved id}`` answers 200    ``performed``      ``confirmed``: the attempt is reattached to
with that id                                                               its reserved conversation
it answers 404                                          ``not_performed``  ``failed`` (terminal)
any other answer, a malformed one, or none              ``indeterminate``  stays ``unknown``
======================================================  =================  ==========================================

The lookup goes through ``AgentServerClient`` on the attempt's pinned route allowlist (the policy it was reserved
under), as every dispatcher call does. A ``confirmed`` attempt is then the same as one ``dispatch`` confirmed: its
conversation is its reserved one, and ``stored_inputs(state='confirmed')`` reads its record. A ``failed`` attempt is
never sent again: ``failed`` is terminal, and a further attempt is a new ordinal with a new conversation id, reserved
by the caller's policy (``reserve_attempt``), never by this module. An ``indeterminate`` lookup leaves the attempt
``unknown`` with reconciliation ``required``: a later ``reconcile_creates`` asks again.

The report is the store's (``confirmed``, ``failed``, ``still_unknown``) with ``observations``: for every key the
oracle was asked about, its verdict and what it was based on (``basis``; for a lookup the HTTP status), in memory
only. Standard library only.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Callable, Mapping

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
store = di.store
DispatchRefused = di.DispatchRefused

PERFORMED, NOT_PERFORMED, INDETERMINATE = 'performed', 'not_performed', 'indeterminate'
CONVERSATION_ROUTE = '/api/conversations/{conversation_id}'   # attempt_end.CONVERSATION_ROUTE, dispatcher-allowed

# What a verdict was based on (an observation's ``basis``).
NOT_IN_NAMESPACE = 'not-in-attempt-namespace'       # no call: another key (a recorder's receipt, a journal)
RECORD_UNREADABLE = 'record-not-a-dispatch-record'  # no call: stored_inputs refused the attempt's record
CONVERSATION_NOT_RESERVED = 'conversation-id-not-reserved'  # no call: the row's id is not the key's uuid5
CLIENT_UNAVAILABLE = 'route-allowlist-unavailable'  # no call: the pinned allowlist cannot be read or checked
CALL_REFUSED = 'call-refused'                       # no call: the client refused the lookup
NO_ANSWER = 'no-answer'                             # the transport raised
LOOKUP = 'lookup'                                   # an HTTP answer: its status is in the observation


def in_namespace(operation_key: str) -> bool:
    """Whether a key is of the typed attempt namespace (``reserve_attempt``'s ``attempt/v1/`` keys)."""
    return isinstance(operation_key, str) and operation_key.startswith(store.KEY_PREFIX)


def verdict_of(answer, conversation_id: str) -> str:
    """The verdict of one answer to ``GET /api/conversations/{conversation_id}``: 200 with that id is performed, 404
    not performed, anything else indeterminate."""
    status = answer.get('status') if isinstance(answer, Mapping) else None
    if type(status) is not int:
        return INDETERMINATE
    if status == 404:
        return NOT_PERFORMED
    body = answer.get('body')
    if status == 200 and isinstance(body, Mapping) and body.get('id') == conversation_id:
        return PERFORMED
    return INDETERMINATE


def _lookup(integration_store, reservation, transport, read_artifact) -> tuple[str, dict]:
    key = reservation.operation_key
    if not in_namespace(key) or integration_store.attempt_identity(key) is None:
        return INDETERMINATE, {'basis': NOT_IN_NAMESPACE}
    try:
        resolved = di.stored_inputs(integration_store, key, state='unknown')
    except DispatchRefused as refusal:
        return INDETERMINATE, {'basis': RECORD_UNREADABLE, 'code': refusal.code}
    conversation_id = reservation.conversation_id
    if conversation_id != store.conversation_id_for(key):
        return INDETERMINATE, {'basis': CONVERSATION_NOT_RESERVED}
    try:
        client = di._attempt_end()._client(resolved, transport)(read_artifact)
    except DispatchRefused as refusal:
        return INDETERMINATE, {'basis': CLIENT_UNAVAILABLE, 'code': refusal.code}
    try:
        answer = client.call('GET', CONVERSATION_ROUTE, params={'conversation_id': conversation_id})
    except DispatchRefused as refusal:
        return INDETERMINATE, {'basis': CALL_REFUSED, 'code': refusal.code}
    except Exception as exc:  # no answer: nothing is inferred from it
        return INDETERMINATE, {'basis': NO_ANSWER, 'error': type(exc).__name__}
    status = answer.get('status') if isinstance(answer, Mapping) else None
    return verdict_of(answer, conversation_id), {'basis': LOOKUP, 'conversationId': conversation_id,
                                                 'httpStatus': status if type(status) is int else None}


def create_oracle(integration_store, *, transport: Callable[[str, str, dict | None], object],
                  read_artifact: Callable[[str], bytes] = di.read_profile_artifact,
                  observations: list | None = None) -> Callable:
    """The oracle for ``IntegrationStore.reconcile`` (the table in the module docstring). It answers only for keys of
    the typed attempt namespace; every other key is ``indeterminate`` and no call is made for it. Each verdict, with
    its basis, is appended to OBSERVATIONS when given."""
    if not callable(transport):
        raise TypeError('transport must be callable as transport(method, path, body)')

    def oracle(reservation) -> str:
        verdict, observed = _lookup(integration_store, reservation, transport, read_artifact)
        if observations is not None:
            observations.append({'operationKey': reservation.operation_key, 'verdict': verdict, **observed})
        return verdict
    return oracle


def reconcile_creates(integration_store, *, transport: Callable[[str, str, dict | None], object], actor: str,
                      read_artifact: Callable[[str], bytes] = di.read_profile_artifact) -> dict:
    """``IntegrationStore.reconcile`` with ``create_oracle``: the store's report and the oracle's observations."""
    observations: list = []
    report = integration_store.reconcile(create_oracle(integration_store, transport=transport,
                                                       read_artifact=read_artifact, observations=observations),
                                         actor=actor)
    return {**report, 'observations': observations}
