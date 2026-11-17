"""The attempt kind's read-only resolver (plan leaf E-01.5; the I1 integration design, R11).

It reads the dispatcher's own records (``integrations/dispatch/dispatch_inputs.py``: ``stored_inputs``, the pinned
route allowlist and the route-checked client), so it is kept apart from ``lineage_resolve.py``, which the acceptance
recorder and the Integration process load and which names no dispatch module (plan leaf P-04.4; the I1 integration
design, R2). ``lineage_resolve.build_registry(attempts=AttemptResolver(...))`` configures it; the shared pieces (the
read-only integration store, the authority vocabulary and its two readers) stay in ``lineage_resolve``.
"""
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def _load(name, path):
    import importlib.util
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


R = _load('lineage_resolve', HERE / 'lineage_resolve.py')
L = R.L
ReadOnlyIntegrationStore = R.ReadOnlyIntegrationStore
_integration_store_module = R._integration_store_module
ATTEMPT_AUTHORITY, FIXTURE, AUTHORITIES = R.ATTEMPT_AUTHORITY, R.FIXTURE, R.AUTHORITIES
CONVERSATION_ROUTE = R.CONVERSATION_ROUTE
declared_authority, answering_authority = R.declared_authority, R.answering_authority


def _dispatch_module():
    """The dispatcher's record readers and route-checked client (``dispatch_inputs``; loaded on first use, only by
    the attempt resolver)."""
    return _load('dispatch_inputs', REPO / 'integrations' / 'dispatch' / 'dispatch_inputs.py')



class AttemptResolver(R.AttemptResolverBase):
    """Execution attempts: the conversation of an attempt the dispatcher dispatched, at the Agent Server, read-only
    (plan leaf E-01.5; the I1 integration design, R11).

    A reference ``openhands:conversation/<id>[@<event>]`` is resolved in this order, each answer named by its code:

    1. the integration store (STORE, opened read-only) holds a reservation whose reserved conversation id is ``<id>``
       (else missing, ATTEMPT_MISSING), in state ``confirmed`` (its create was answered with the reserved id; else
       missing, ATTEMPT_NOT_CONFIRMED), and that reservation is the dispatcher's record of a typed attempt
       (``dispatch_inputs.stored_inputs``; else authority-unavailable, ATTEMPT_RECORD_INVALID);
    2. the attempt's **bound authority** is its pinned route allowlist's declaration (``declared_authority``: the
       allowlist read by its pinned sha256 through READ_ARTIFACT; else authority-unavailable,
       ATTEMPT_ALLOWLIST_UNREADABLE);
    3. the Agent Server, through TRANSPORT and the route-checked client over that allowlist, is asked ``GET
       /api/conversations/{id}`` once (no answer: authority-unavailable, ATTEMPT_UNANSWERED);
    4. the **answering authority** (``answering_authority``: the answer's fixture label, or ``live``) must equal the
       bound one (else authority-unavailable, ATTEMPT_AUTHORITY_MISMATCH: a fixture-bound attempt answered without
       the label, or a label on a live-bound one, is neither);
    5. a 404 is missing (ATTEMPT_CONVERSATION_MISSING); a 200 whose body names ``<id>`` is resolved, its observed
       digest the sha256 of ``{"id": <id>}`` as the server answered it (identity, not the conversation's state); any
       other answer is authority-unavailable (ATTEMPT_UNOBSERVED);
    6. a pinned ``@<event>`` is not resolved (authority-unavailable, ATTEMPT_EVENT_UNOBSERVED): the native event
       id's form is not observed (the kind's open item), so the resolver cannot tell an event from its absence;
       ``current`` ignores the anchor.

    A resolution the fixture answered carries ``lineage.fixture_authority`` of the kind's authority as its label,
    so that a traversal states its mode ``fixture``; the mode is the resolver's own finding per reference, never a
    caller's flag. Read-only: the store is opened ``mode=ro`` and the server is asked one ``GET``."""
    kind = 'attempt'
    authority = ATTEMPT_AUTHORITY
    outcomes = frozenset({L.RESOLVED, L.MISSING, L.AUTHORITY_UNAVAILABLE})

    def __init__(self, store, transport, read_artifact=None):
        self.store, self.transport, self._read_artifact = Path(store), transport, read_artifact

    def resolve(self, reference):
        return self._ask(reference, 'reference')

    def current(self, reference):
        return self._ask(reference, 'current')

    def _ask(self, reference, query):
        def say(outcome, code=None, detail='', authority=ATTEMPT_AUTHORITY, **extra):
            return L.answer(reference, outcome, authority, code, detail, query=query, **extra)

        store_mod = _integration_store_module()
        try:
            with ReadOnlyIntegrationStore(self.store) as store:
                record = self._record(store, reference, say)
        except (store_mod.StoreError, sqlite3.Error, OSError) as exc:
            return say(L.AUTHORITY_UNAVAILABLE, 'INTEGRATION_STORE_UNAVAILABLE', f'{type(exc).__name__}: {exc}')
        if isinstance(record, L.Resolution):
            return record
        return self._at_server(reference, query, record, say)

    def _record(self, store, reference, say):
        """The attempt's (resolved inputs, its pinned allowlist's bytes and pin) from the store, or a Resolution."""
        di = _dispatch_module()
        held = [r for r in store.attempts() if r.conversation_id == reference.conversation]
        if not held:
            return say(L.MISSING, 'ATTEMPT_MISSING',
                       f'the integration store holds no attempt whose reserved conversation is {reference.conversation}')
        (reservation,) = held          # a conversation id is the uuid5 of one operation key
        if reservation.state != 'confirmed':
            return say(L.MISSING, 'ATTEMPT_NOT_CONFIRMED', f'the attempt {reservation.operation_key!r} is '
                       f'{reservation.state}: no create of it was answered with its conversation')
        try:
            resolved = di.stored_inputs(store, reservation.operation_key, state='confirmed')
        except di.DispatchRefused as refusal:
            return say(L.AUTHORITY_UNAVAILABLE, 'ATTEMPT_RECORD_INVALID',
                       f'{reservation.operation_key!r} is not the dispatcher\'s record of a typed attempt '
                       f'({refusal.code})')
        try:
            pin = di._resolved_admission(resolved)['routes']
            allowlist = di._read_pinned(self._read_artifact or di.read_profile_artifact, pin, 'route allowlist')
        except di.DispatchRefused as refusal:
            return say(L.AUTHORITY_UNAVAILABLE, 'ATTEMPT_ALLOWLIST_UNREADABLE',
                       f'the attempt\'s pinned route allowlist cannot be read ({refusal.code})')
        return resolved, allowlist, pin

    def _at_server(self, reference, query, record, say):
        di = _dispatch_module()
        _resolved, allowlist, pin = record
        bound = declared_authority(allowlist)
        if bound is None:
            return say(L.AUTHORITY_UNAVAILABLE, 'ATTEMPT_ALLOWLIST_UNREADABLE',
                       'the attempt\'s pinned route allowlist declares no authority of ' + ', '.join(AUTHORITIES))
        conversation = reference.conversation
        try:
            client = di.AgentServerClient(allowlist, self.transport, routes_sha256=pin['sha256'])
            answer = client.call('GET', CONVERSATION_ROUTE, params={'conversation_id': conversation})
        except Exception as exc:  # noqa: BLE001 - no answer: nothing is inferred from it
            return say(L.AUTHORITY_UNAVAILABLE, 'ATTEMPT_UNANSWERED',
                       f'the Agent Server did not answer for conversation {conversation} ({type(exc).__name__})')
        answered = answering_authority(answer)
        if answered != bound:
            return say(L.AUTHORITY_UNAVAILABLE, 'ATTEMPT_AUTHORITY_MISMATCH',
                       f'the attempt is bound to authority {bound!r} and was answered by {answered!r}')
        authority = L.fixture_authority(ATTEMPT_AUTHORITY) if answered == FIXTURE else ATTEMPT_AUTHORITY
        status = answer.get('status') if isinstance(answer, dict) else None
        if status == 404:
            return say(L.MISSING, 'ATTEMPT_CONVERSATION_MISSING',
                       f'the Agent Server does not hold conversation {conversation}', authority=authority)
        body = answer.get('body') if isinstance(answer, dict) else None
        if status != 200 or not isinstance(body, dict) or body.get('id') != conversation:
            return say(L.AUTHORITY_UNAVAILABLE, 'ATTEMPT_UNOBSERVED',
                       f'the Agent Server answered {status!r} without the conversation', authority=authority)
        if query == 'reference' and reference.event is not None:
            return say(L.AUTHORITY_UNAVAILABLE, 'ATTEMPT_EVENT_UNOBSERVED',
                       f'event {reference.event!r}: the native event id\'s form is not observed, so a pinned event '
                       'is not resolved', authority=authority)
        digest = hashlib.sha256(json.dumps({'id': body['id']}, sort_keys=True, separators=(',', ':'))
                                .encode('utf-8')).hexdigest()
        return say(L.RESOLVED, detail=f'conversation {conversation} of the dispatched attempt (bound and answered '
                   f'{answered})', authority=authority, observed_digest=digest)
