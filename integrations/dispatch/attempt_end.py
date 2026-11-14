"""The end of a provider-interrupted native attempt and the admission of a new attempt for the same task (plan leaf
E-05.8, decision 0023; the Owner's direction of 2026-11-13: no new resumption framework).

D1 does not resume a conversation. The pinned sources (the Claude Code ACP adapter 0.63.0, the CLI 2.1.220 it runs,
the SDK's ACPAgent and the Agent Server 1.60.1) are read in the E-05.8 determination record; whatever they offer, an
interrupted attempt is ended and a new attempt, with a new conversation, is admitted after that end.

``end_interrupted_attempt(store, operation_key, transport=, actor=, trigger=, dispatcher_records=())`` ends a
confirmed native attempt whose conversation ended (trigger ``conversation-ended``) or which the dispatcher stops
(``attempt-stopped``):

1. the attempt's dispatch record re-read from the store, ``confirmed`` (RESERVATION_INVALID,
   ATTEMPT_NOT_CONFIRMED), and not of the brokered profile (ATTEMPT_PROFILE_BROKERED: E-05.6's ``end_attempt``);
2. an end already recorded is returned as it is, with no call;
3. on a first end, the conversation's recorded status and events are read: a conversation still ``running`` is not
   ended as ``conversation-ended`` (CONVERSATION_STILL_RUNNING), and a ``finished`` one with no interruption and no
   security stop is the result path's (ATTEMPT_NOT_INTERRUPTED); nothing is written then;
4. the end journal ``dispatch/attempt/<attempt id>/end`` is reserved, then ``dispatched`` with the trigger and the
   dispatcher's records, before the runtime is stopped (``DELETE .../runtime``) and observed stopped (``GET
   .../runtime`` answers ``missing``; RUNTIME_NOT_STOPPED otherwise);
5. the conversation's recorded status and events are read again, whole (CONVERSATION_UNOBSERVED), and classified
   (``classify``) with the dispatcher's own records;
6. the journal is ``confirmed`` with the end record (``attempt-end/v1``: attempt, conversation, classification, the
   surfaced codes and statuses, the token's fingerprint only). That is the one end record of the attempt.

A repeat after a crash resumes the journal where it stopped (after the runtime stopped, it stops it again, which the
server treats as done, and records); a repeat after the record returns it. The attempt's own receipt, the task's
Backlog.md and OpenSpec records are not touched, and nothing is handed to the result path: the end calls no result
or workspace route.

``admit_new_attempt(store, resolved, transport=, read_artifact=)`` runs in ``dispatch_inputs.dispatch`` before the
reservation. Every earlier attempt on the work item, design revision and stage that created a native conversation
(confirmed, its dispatched transition carrying the native token's fingerprint) must have an end record
(PRIOR_ATTEMPT_NOT_ENDED); none may have ended non-retryable (PRIOR_END_SECURITY_STOP, the leaf's security stop) or
unclassified (PRIOR_END_UNCLASSIFIED); each runtime must be observed stopped now (PRIOR_CONVERSATION_RUNNING,
PRIOR_CONVERSATION_UNOBSERVED); an authentication refusal needs the engineering manager's cause record
(PRIOR_AUTH_CAUSE_UNRECORDED), and where the provider refused the token, a native-token entry receipt newer than
that attempt's dispatch whose token is another (PRIOR_AUTH_TOKEN_NOT_REPLACED); the token then read must be that
receipt's (NATIVE_TOKEN_NOT_REPLACED). The new attempt is the next ordinal, so it has a new conversation id: the
token is never sent to an existing conversation.

``record_auth_cause(store, operation_key, cause=, actor=)`` is the engineering manager's cause record, the smallest
durable form: one integration-store receipt ``dispatch/attempt/<attempt id>/auth-cause`` (``auth-cause/v1``),
written by the command ``record-auth-cause`` of this module. ``record_end_cause`` (command ``record-end-cause``) is
the engineering manager's classification of an unclassified end, ``interruption`` or ``security-stop``, as one
receipt ``dispatch/attempt/<attempt id>/end-cause`` (``end-cause/v1``); the end record never changes, and a new
attempt after an unclassified end stays PRIOR_END_UNCLASSIFIED until it exists. Fingerprints only, here as
everywhere.

Standard library only. It holds no token and reads no credential entry: the entry receipts it reads are the
credential command's integration-store receipts (``aieh-credential-act/1``), fingerprints only.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Sequence

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


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

END_KEY = 'dispatch/attempt/{attempt_id}/end'
END_JOURNAL_FORMAT = 'ai-engineering-harness/dispatch/attempt-end-journal/v1'
END_FORMAT = 'ai-engineering-harness/dispatch/attempt-end/v1'
CAUSE_KEY = 'dispatch/attempt/{attempt_id}/auth-cause'
CAUSE_FORMAT = 'ai-engineering-harness/dispatch/auth-cause/v1'
END_CAUSE_KEY = 'dispatch/attempt/{attempt_id}/end-cause'
END_CAUSE_FORMAT = 'ai-engineering-harness/dispatch/end-cause/v1'
CONVERSATION_ENDED, ATTEMPT_STOPPED = 'conversation-ended', 'attempt-stopped'
TRIGGERS = (CONVERSATION_ENDED, ATTEMPT_STOPPED)

# The classification (the delegated mapping; the table is in README.md and the determination record).
INTERRUPTION = 'interruption'                      # retryable: a new attempt after the end
AUTH_REFUSAL = 'authentication-refusal'            # an interruption that needs the Owner
NON_RETRYABLE = 'non-retryable'                    # a security stop: no new attempt
UNCLASSIFIED = 'unclassified'                      # no provider interruption surfaced: no new attempt here
CLASSIFICATIONS = (INTERRUPTION, AUTH_REFUSAL, NON_RETRYABLE, UNCLASSIFIED)
USAGE_LIMIT, OVERLOAD, STREAM_CUT, PATH_LOST = 'usage-limit', 'overload', 'stream-cut', 'path-lost'
AUTHENTICATION = 'authentication'
INTERRUPTION_CAUSES = (USAGE_LIMIT, OVERLOAD, STREAM_CUT, PATH_LOST)

# The dispatcher's own records: what it observed itself about the attempt (never the conversation's say-so).
NON_RETRYABLE_RECORDS = {'containment-stop': 'containment', 'credential-stop': 'credential',
                         'egress-stop': 'unexpected-egress'}
INTERRUPTION_RECORDS = {'provider-path-lost': PATH_LOST}
RECORD_KINDS = (*NON_RETRYABLE_RECORDS, *INTERRUPTION_RECORDS)
RECORD_REF_RE = re.compile(r'[A-Za-z0-9._:/@#-]{1,256}')

# The engineering manager's causes of an authentication refusal; only token-refused needs a new token entered.
TOKEN_REFUSED = 'token-refused'
AUTH_CAUSES = (TOKEN_REFUSED, 'account-not-permitted', 'provider-fault')
# The engineering manager's classification of an unclassified end: an interruption (a new attempt as after any
# interruption's end) or a security stop (no new attempt, ever: PRIOR_END_SECURITY_STOP).
END_CAUSE_INTERRUPTION, END_CAUSE_SECURITY_STOP = 'interruption', 'security-stop'
END_CAUSES = (END_CAUSE_INTERRUPTION, END_CAUSE_SECURITY_STOP)

# The Agent Server 1.60.1 routes the end reads and calls (all `dispatcher: allowed` in the pinned allowlist).
CONVERSATION_ROUTE = '/api/conversations/{conversation_id}'
EVENTS_ROUTE = '/api/conversations/{conversation_id}/events/search'
RUNTIME_ROUTE = '/api/conversations/{conversation_id}/runtime'
STOPPED = 'missing'          # ConversationRuntimeStatus.MISSING: no container runs or starts (registry.py runtime_info)
EXECUTION_STATUSES = ('idle', 'running', 'paused', 'waiting_for_confirmation', 'finished', 'error', 'stuck',
                      'deleting')   # ConversationExecutionStatus (sdk conversation/state.py)
MAX_EVENT_PAGES = 200        # 100 events a page (the route's default): 20,000 events, else CONVERSATION_UNOBSERVED

# What the pinned sources surface (cited in the determination record). A ConversationErrorEvent's code is the SDK's
# (acp_agent.py _classify_acp_init_error, _classify_acp_turn_error; local_conversation.py); for the ACP codes its
# detail is ``[<JSON-RPC code>] <message>: <data>`` (acp_agent.py _acp_error_detail), the message the CLI's API
# error text and the data the adapter's ``{"errorKind": <the CLI's assistant error kind>}``.
ERROR_EVENT = 'ConversationErrorEvent'
EVENT_CODE_RE = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,63}')
AUTH_CODES = frozenset({'ACPAuthRequired', 'LLMAuthenticationError'})
DETAIL_CODES = frozenset({'ACPPromptError', 'ACPInitError', 'ACPStartupTimeout', 'LLMRateLimitError'})
ERROR_KIND_RE = re.compile(r'"errorKind":\s*"([a-z_]{1,64})"')
CONNECTION_LOST_RE = re.compile(r'Connection to the API was lost \(([A-Za-z_]{1,64})\)')
UNABLE_TO_CONNECT_RE = re.compile(r'Unable to connect to API \(([A-Za-z_]{1,64})\)')
STATUS_RE = re.compile(r'\b([45]\d\d)\b')
# The CLI's connection code sets (claude 2.1.220 @252005005): a dropped connection, and a path never opened.
STREAM_CUT_CODES = frozenset({'ECONNRESET', 'EPIPE', 'ConnectionClosed', 'ETIMEDOUT', 'ECONNABORTED',
                              'ERR_SOCKET_CLOSED', 'StreamSuspended'})
PATH_LOST_CODES = frozenset({'ECONNREFUSED', 'ConnectionRefused', 'ENOTFOUND', 'ENETUNREACH', 'ENETDOWN',
                             'EHOSTUNREACH', 'EHOSTDOWN', 'EAI_AGAIN', 'FailedToOpenSocket', 'ERR_PROXY_TUNNEL'})
AUTH_KINDS = frozenset({'authentication_failed', 'oauth_org_not_allowed'})
USAGE_KINDS = frozenset({'rate_limit', 'billing_error'})
# The CLI's own texts (2.1.220): the request timed out (@252038121 tct), the connection slept (lir), no connection.
STREAM_CUT_TEXTS = ('Request timed out', 'Connection interrupted by system sleep')
PATH_LOST_TEXTS = ('Unable to connect to API. Check your internet connection',)
# ... and the provider's overload: repeated 529s (@252038008 P7r) and a 5xx (ley's server-side text, @252027146).
OVERLOAD_TEXTS = ('Repeated 529 Overloaded errors', 'This is a server-side issue')

# The native-token entry receipts (integrations/credentials native_token_entry.py SERVICE, credential_provider.py
# RECEIPT_FORMAT; a test pins both): read from the store, fingerprints only, never the credential provider.
ENTRY_RECEIPT_FORMAT = 'aieh-credential-act/1'
ENTRY_RECEIPT_PREFIX = 'credential/dispatch-native-token/'


def _refused(code: str, detail: str, **context) -> DispatchRefused:
    return DispatchRefused(code, detail, **context)


def _loads(text):
    try:
        return di._strict_loads(text or 'null')
    except ValueError:
        return None


def _detail(integration_store, key: str, to_state: str):
    """The detail of KEY's last transition into TO_STATE, or None."""
    for event in reversed(integration_store.events(key)):
        if event.to_state == to_state:
            return _loads(event.detail_json)
    return None


def _event_id(integration_store, key: str, to_state: str) -> int | None:
    for event in reversed(integration_store.events(key)):
        if event.to_state == to_state:
            return event.event_id
    return None


def native_fingerprint(integration_store, operation_key: str) -> str | None:
    """The native token's fingerprint the attempt's dispatched transition records (E-05.9), or None: an attempt
    without one created no native conversation."""
    detail = _detail(integration_store, operation_key, 'dispatched')
    held = detail.get('nativeToken') if isinstance(detail, dict) else None
    fingerprint = held.get('tokenFingerprint') if isinstance(held, dict) else None
    shape = di._native_module().FINGERPRINT_SHAPE
    return fingerprint if isinstance(fingerprint, str) and shape.fullmatch(fingerprint) else None


def end_record(integration_store, attempt_id: str) -> dict | None:
    """The attempt's one end record (its end journal, confirmed), or None."""
    key = END_KEY.format(attempt_id=attempt_id)
    held = integration_store.get(key)
    if held is None or held.state != 'confirmed':
        return None
    record = _detail(integration_store, key, 'confirmed')
    return record if isinstance(record, dict) and record.get('format') == END_FORMAT else None


def _confirmed_record(integration_store, key: str, form: str) -> dict | None:
    held = integration_store.get(key)
    if held is None or held.state != 'confirmed':
        return None
    record = _detail(integration_store, key, 'confirmed')
    return record if isinstance(record, dict) and record.get('format') == form else None


def cause_record(integration_store, attempt_id: str) -> dict | None:
    """The engineering manager's cause record of an authentication refusal (auth-cause/v1), or None."""
    return _confirmed_record(integration_store, CAUSE_KEY.format(attempt_id=attempt_id), CAUSE_FORMAT)


def end_cause_record(integration_store, attempt_id: str) -> dict | None:
    """The engineering manager's classification of an unclassified end (end-cause/v1), or None."""
    return _confirmed_record(integration_store, END_CAUSE_KEY.format(attempt_id=attempt_id), END_CAUSE_FORMAT)


def effective_classification(integration_store, record: dict) -> str | None:
    """An end record's classification, or for an unclassified end the engineering manager's: interruption or
    non-retryable by its end-cause record, unclassified while none exists. The end record itself never changes."""
    classification = record.get('classification')
    if classification != UNCLASSIFIED:
        return classification
    cause = end_cause_record(integration_store, record.get('attemptId'))
    if cause is None:
        return UNCLASSIFIED
    return {END_CAUSE_INTERRUPTION: INTERRUPTION, END_CAUSE_SECURITY_STOP: NON_RETRYABLE}.get(cause.get('cause'),
                                                                                            UNCLASSIFIED)


# ---------------------------------------------------------------------------
# Classification: from the conversation's recorded status and events and the dispatcher's own records

def check_records(records) -> list[dict]:
    """The dispatcher's own records, each exactly {kind, code, ref} in its grammar (DISPATCHER_RECORD_INVALID)."""
    if not isinstance(records, (list, tuple)):
        raise _refused('DISPATCHER_RECORD_INVALID', 'the dispatcher records are not a list')
    out = []
    for n, record in enumerate(records):
        if not isinstance(record, Mapping) or set(record) != {'kind', 'code', 'ref'} \
                or record['kind'] not in RECORD_KINDS or not isinstance(record['code'], str) \
                or di.CODE_RE.fullmatch(record['code']) is None or not isinstance(record['ref'], str) \
                or RECORD_REF_RE.fullmatch(record['ref']) is None:
            raise _refused('DISPATCHER_RECORD_INVALID', f'dispatcher record {n} is not {{kind, code, ref}} of its '
                           f'grammar (kinds: {", ".join(RECORD_KINDS)})', index=n)
        out.append({'kind': record['kind'], 'code': record['code'], 'ref': record['ref']})
    return out


def error_signal(event: Mapping) -> dict:
    """What one ConversationErrorEvent surfaced: its id, source and code, the adapter's error kind and the CLI's
    connection code found in its detail, the status numbers its detail names (recorded, never classified alone),
    the SDK's own classification kind, and the cause it is read as (or None). Nothing of the detail's text is kept."""
    code = event.get('code') if isinstance(event.get('code'), str) else ''
    detail = event.get('detail') if isinstance(event.get('detail'), str) else ''
    sdk = event.get('classification')
    signal = {'eventId': event.get('id') if isinstance(event.get('id'), str) else None,
              'source': event.get('source') if isinstance(event.get('source'), str) else None,
              'code': code if EVENT_CODE_RE.fullmatch(code) else '<invalid>',
              'errorKind': None, 'connectionCode': None,
              'statuses': sorted(set(STATUS_RE.findall(detail)))[:8],
              'sdkKind': sdk.get('kind') if isinstance(sdk, Mapping) and isinstance(sdk.get('kind'), str) else None,
              'cause': None}
    kind = ERROR_KIND_RE.search(detail)
    signal['errorKind'] = kind.group(1) if kind else None
    connection = CONNECTION_LOST_RE.search(detail) or UNABLE_TO_CONNECT_RE.search(detail)
    signal['connectionCode'] = connection.group(1) if connection else None
    if code in AUTH_CODES:
        signal['cause'] = AUTHENTICATION
    elif code in DETAIL_CODES:
        error_kind, conn = signal['errorKind'], signal['connectionCode']
        if code == 'LLMRateLimitError':
            signal['cause'] = USAGE_LIMIT
        elif error_kind in AUTH_KINDS:
            signal['cause'] = AUTHENTICATION
        elif error_kind in USAGE_KINDS:
            signal['cause'] = USAGE_LIMIT
        elif error_kind == 'server_error':
            if conn in STREAM_CUT_CODES or (conn is None and any(t in detail for t in STREAM_CUT_TEXTS)):
                signal['cause'] = STREAM_CUT
            elif conn in PATH_LOST_CODES or (conn is None and any(t in detail for t in PATH_LOST_TEXTS)):
                signal['cause'] = PATH_LOST
            elif conn is None and any(t in detail for t in OVERLOAD_TEXTS):
                signal['cause'] = OVERLOAD      # repeated 529, a 5xx (an SSL failure or another text: none)
    return signal


def classify(execution_status, events, records) -> dict:
    """The classification of an attempt's end from the conversation's recorded status (EXECUTION_STATUS) and events
    (EVENTS, the event search's items) and the dispatcher's own records (RECORDS, check_records'): a security stop
    of the dispatcher's is non-retryable whatever the conversation says; else an authentication signal is an
    authentication refusal (an interruption that needs the Owner); else a usage or rate limit, an overload, a cut
    stream or a lost path (the conversation's, or the dispatcher's own provider-path record) is an interruption;
    else unclassified. Only ConversationErrorEvents are read as signals: no agent message, observation or HTTP
    status alone classifies anything."""
    signals = [error_signal(e) for e in events if isinstance(e, Mapping) and e.get('kind') == ERROR_EVENT]
    security = sorted({NON_RETRYABLE_RECORDS[r['kind']] for r in records if r['kind'] in NON_RETRYABLE_RECORDS})
    interrupted = [s['cause'] for s in signals if s['cause'] in INTERRUPTION_CAUSES] + \
                  [INTERRUPTION_RECORDS[r['kind']] for r in records if r['kind'] in INTERRUPTION_RECORDS]
    if security:
        classification, causes = NON_RETRYABLE, security
    elif any(s['cause'] == AUTHENTICATION for s in signals):
        classification, causes = AUTH_REFUSAL, [AUTHENTICATION]
    elif interrupted:
        classification, causes = INTERRUPTION, sorted(set(interrupted))
    else:
        classification, causes = UNCLASSIFIED, []
    return {'classification': classification, 'causes': causes,
            'retryable': classification in (INTERRUPTION, AUTH_REFUSAL),
            'needsOwner': classification == AUTH_REFUSAL,
            'securityStop': classification == NON_RETRYABLE,
            'surfaced': {'executionStatus': execution_status, 'errorEvents': signals,
                         'dispatcherRecords': [dict(r) for r in records]}}


# ---------------------------------------------------------------------------
# The Agent Server reads and the runtime stop (the route-checked client only)

def _client(resolved, transport) -> Callable:
    """A factory of the route-checked client for the attempt's pinned route allowlist (its policy inputs)."""
    def make(read_artifact):
        admission = di._resolved_admission(resolved)
        raw = di._read_pinned(read_artifact, admission['routes'], 'route allowlist')
        return di.AgentServerClient(raw, transport, routes_sha256=admission['routes']['sha256'])
    return make


def _answer(client, method, route, conversation_id, code, what, **kwargs):
    """One call: its HTTP answer as {status, body}, or CODE when there is none or it is not of that shape."""
    try:
        answer = client.call(method, route, params={'conversation_id': conversation_id}, **kwargs)
    except DispatchRefused:
        raise
    except Exception as exc:  # no answer: nothing is inferred from it
        raise _refused(code, f'{what}: no answer ({type(exc).__name__})') from None
    status = answer.get('status') if isinstance(answer, Mapping) else None
    if type(status) is not int:
        raise _refused(code, f'{what}: not an HTTP answer')
    return status, answer.get('body')


def observe(client, conversation_id: str) -> tuple[str, list]:
    """The conversation's recorded execution status and its events, whole: GET the conversation (its
    ConversationInfo's execution_status), then every page of the event search (page_id the previous page's
    next_page_id). Anything but a 200 of the expected shape, a repeated page or more than MAX_EVENT_PAGES pages is
    CONVERSATION_UNOBSERVED (a 404 of the conversation is CONVERSATION_NOT_FOUND). Read from the outer server's
    persisted catalog (the Docker registry's execution routes include the persisted event reads), so a read does
    not start the runtime."""
    status, body = _answer(client, 'GET', CONVERSATION_ROUTE, conversation_id, 'CONVERSATION_UNOBSERVED',
                           'the conversation')
    if status == 404:
        raise _refused('CONVERSATION_NOT_FOUND', f'the Agent Server does not know conversation {conversation_id}')
    execution = body.get('execution_status') if isinstance(body, Mapping) else None
    if status != 200 or execution not in EXECUTION_STATUSES or body.get('id') != conversation_id:
        raise _refused('CONVERSATION_UNOBSERVED', f'the conversation answered {status} without its execution status',
                       status=status)
    events, page, seen = [], None, set()
    for _ in range(MAX_EVENT_PAGES):
        query = None if page is None else {'page_id': page}
        status, body = _answer(client, 'GET', EVENTS_ROUTE, conversation_id, 'CONVERSATION_UNOBSERVED',
                               'the event search', query=query)
        items = body.get('items') if isinstance(body, Mapping) else None
        following = body.get('next_page_id') if isinstance(body, Mapping) else None
        if status != 200 or not isinstance(items, list) or not (following is None or isinstance(following, str)):
            raise _refused('CONVERSATION_UNOBSERVED', f'the event search answered {status} without a page',
                           status=status)
        events.extend(items)
        if following is None:
            return execution, events
        if following in seen or di.ROUTE_PARAMETERS['event_id'].fullmatch(following) is None:
            raise _refused('CONVERSATION_UNOBSERVED', 'the event search repeated a page or named an invalid one')
        seen.add(following)
        page = following
    raise _refused('CONVERSATION_UNOBSERVED', f'the event search has more than {MAX_EVENT_PAGES} pages')


def runtime_status(client, conversation_id: str, code: str) -> str | None:
    """The runtime's status (GET .../runtime: ConversationRuntimeInfo.runtime_status), or None when the server does
    not know the conversation (404: nothing of it runs). Anything else is CODE."""
    status, body = _answer(client, 'GET', RUNTIME_ROUTE, conversation_id, code, 'the runtime')
    if status == 404:
        return None
    value = body.get('runtime_status') if isinstance(body, Mapping) else None
    if status != 200 or not isinstance(value, str):
        raise _refused(code, f'the runtime answered {status} without its status', status=status)
    return value


def stop_runtime(client, conversation_id: str) -> str:
    """Stop the runtime (DELETE .../runtime: the container is stopped and the conversation's state kept;
    docker_runtime/routers.py release_runtime answers 204, also when nothing runs) and observe it stopped (GET
    .../runtime: ``missing``). RUNTIME_NOT_STOPPED or CONVERSATION_NOT_FOUND otherwise."""
    status, _ = _answer(client, 'DELETE', RUNTIME_ROUTE, conversation_id, 'RUNTIME_NOT_STOPPED', 'the runtime stop')
    if status == 404:
        raise _refused('CONVERSATION_NOT_FOUND', f'the Agent Server does not know conversation {conversation_id}')
    if status != 204:
        raise _refused('RUNTIME_NOT_STOPPED', f'the runtime stop answered {status}', status=status)
    observed = runtime_status(client, conversation_id, 'RUNTIME_NOT_STOPPED')
    if observed != STOPPED:
        raise _refused('RUNTIME_NOT_STOPPED', f'the runtime is observed {observed!r}, not {STOPPED!r}',
                       runtime_status=observed)
    return observed


# ---------------------------------------------------------------------------
# The end

def end_interrupted_attempt(integration_store, operation_key: str, *, transport, actor: str, trigger: str,
                            dispatcher_records: Sequence[Mapping] = (),
                            read_artifact: Callable[[str], bytes] = di.read_profile_artifact) -> dict:
    """End a confirmed native attempt that an interruption stopped (the module docstring's steps 1 to 6) and return
    its one end record (``attempt-end/v1``). Repeat-safe: a repeat returns the record; a repeat after a crash
    resumes the journal as it began (the same trigger and records, else ATTEMPT_END_CONFLICT)."""
    if trigger not in TRIGGERS:
        raise ValueError(f'trigger must be one of {TRIGGERS}')
    records = check_records(list(dispatcher_records))
    resolved = di.stored_inputs(integration_store, operation_key, state='confirmed')
    attempt_id = store.attempt_id_for(operation_key)
    conversation_id = store.conversation_id_for(operation_key)
    if integration_store.get(di.GRANT_JOURNAL_KEY.format(attempt_id=attempt_id)) is not None:
        raise _refused('ATTEMPT_PROFILE_BROKERED', f'attempt {attempt_id} holds a broker grant journal: '
                       'end_attempt ends it, with the revocation')
    key = END_KEY.format(attempt_id=attempt_id)
    held = integration_store.get(key)
    if held is not None and held.state == 'confirmed':
        return _detail(integration_store, key, 'confirmed')
    begun = {'trigger': trigger, 'dispatcherRecords': records}
    client = _client(resolved, transport)(read_artifact)
    if held is None:
        execution, events = observe(client, conversation_id)   # read only: nothing is written on a refusal here
        if trigger == CONVERSATION_ENDED and execution == 'running':
            raise _refused('CONVERSATION_STILL_RUNNING', f'conversation {conversation_id} is running: it has not ended',
                           execution_status=execution)
        if execution == 'finished' and not any(r['kind'] in NON_RETRYABLE_RECORDS for r in records):
            raise _refused('ATTEMPT_NOT_INTERRUPTED', f'conversation {conversation_id} finished and no security stop '
                           'is recorded: its result is the result path\'s', execution_status=execution)
        intent = {'format': END_JOURNAL_FORMAT, 'operationKey': operation_key, 'attemptId': attempt_id,
                  'conversationId': conversation_id}
        integration_store.reserve(key, intent, actor=actor)
        di._mark(integration_store, key, 'reserved', 'dispatched', actor, 'stop-runtime', begun)
    elif held.state == 'reserved':   # a crash between the reservation and its dispatch: nothing was stopped yet
        di._mark(integration_store, key, 'reserved', 'dispatched', actor, 'stop-runtime', begun)
    elif held.state == 'dispatched':
        if _detail(integration_store, key, 'dispatched') != begun:
            raise _refused('ATTEMPT_END_CONFLICT', f'the end of attempt {attempt_id} began with another trigger or '
                           'other dispatcher records')
    else:
        raise _refused('ATTEMPT_END_CONFLICT', f'the end journal of attempt {attempt_id} is {held.state}')
    runtime = stop_runtime(client, conversation_id)
    execution, events = observe(client, conversation_id)
    verdict = classify(execution, events, records)
    identity = integration_store.attempt_identity(operation_key).identity
    record = {'format': END_FORMAT, 'operationKey': operation_key, 'attemptId': attempt_id,
              'conversationId': conversation_id, 'executionRef': f'{di.EXECUTION_REF_PREFIX}{conversation_id}',
              'workId': identity.work_id, 'designRevision': identity.design_revision, 'stage': identity.stage,
              'ordinal': identity.ordinal, 'trigger': trigger,
              'classification': verdict['classification'], 'causes': verdict['causes'],
              'retryable': verdict['retryable'], 'needsOwner': verdict['needsOwner'],
              'securityStop': verdict['securityStop'],
              'surfaced': {**verdict['surfaced'], 'runtimeStatus': runtime},
              'conversationStopped': True, 'resultHandedOn': False,
              'tokenFingerprint': native_fingerprint(integration_store, operation_key)}
    di._mark(integration_store, key, 'dispatched', 'confirmed', actor, verdict['classification'], record)
    return _detail(integration_store, key, 'confirmed')


# ---------------------------------------------------------------------------
# The engineering manager's cause record

def record_auth_cause(integration_store, operation_key: str, *, cause: str, actor: str) -> dict:
    """The engineering manager's record of an authentication refusal's cause: one receipt
    ``dispatch/attempt/<attempt id>/auth-cause`` (reserved, dispatched, confirmed with ``auth-cause/v1``). Only for
    an attempt whose end record is an authentication refusal (AUTH_CAUSE_NOT_APPLICABLE); CAUSE is one of
    AUTH_CAUSES (AUTH_CAUSE_INVALID); recording the same cause again returns it, another is AUTH_CAUSE_CONFLICT.
    ``tokenRefused`` (the cause token-refused) carries the refused token's fingerprint, from the end record."""
    if cause not in AUTH_CAUSES:
        raise _refused('AUTH_CAUSE_INVALID', f'the cause must be one of {", ".join(AUTH_CAUSES)}')
    if integration_store.get(operation_key) is None or integration_store.attempt_identity(operation_key) is None:
        raise _refused('RESERVATION_INVALID', f'no dispatch reservation under {operation_key!r}')
    attempt_id = store.attempt_id_for(operation_key)
    ended = end_record(integration_store, attempt_id)
    if ended is None or ended.get('classification') != AUTH_REFUSAL:
        raise _refused('AUTH_CAUSE_NOT_APPLICABLE', f'attempt {attempt_id} has no end record of an authentication '
                       'refusal')
    key = CAUSE_KEY.format(attempt_id=attempt_id)
    intent = {'format': CAUSE_FORMAT, 'operationKey': operation_key, 'attemptId': attempt_id,
              'conversationId': store.conversation_id_for(operation_key), 'cause': cause,
              'tokenRefused': cause == TOKEN_REFUSED,
              'refusedFingerprint': ended.get('tokenFingerprint') if cause == TOKEN_REFUSED else None,
              'endRecord': END_KEY.format(attempt_id=attempt_id)}
    _write_cause(integration_store, key, intent, actor, 'AUTH_CAUSE_CONFLICT')
    return cause_record(integration_store, attempt_id)


def _write_cause(integration_store, key: str, intent: dict, actor: str, conflict: str) -> None:
    """One cause receipt: reserved with INTENT, dispatched, confirmed with INTENT and ``recordedBy``; a resumed or
    repeated write with the same intent completes or returns it, another intent is CONFLICT."""
    try:
        integration_store.reserve(key, intent, actor=actor)
    except store.ConflictingReservation:
        raise _refused(conflict, f'another cause is recorded under {key}') from None
    held = integration_store.get(key)
    if held.state == 'reserved':
        di._mark(integration_store, key, 'reserved', 'dispatched', actor, 'record', None)
        held = integration_store.get(key)
    if held.state == 'dispatched':
        di._mark(integration_store, key, 'dispatched', 'confirmed', actor, intent['cause'],
                 {**intent, 'recordedBy': actor})


def record_end_cause(integration_store, operation_key: str, *, cause: str, actor: str) -> dict:
    """The engineering manager's classification of an unclassified end: one receipt
    ``dispatch/attempt/<attempt id>/end-cause`` (``end-cause/v1``), beside the end record, which never changes. CAUSE
    is ``interruption`` (a new attempt is admitted as after any interruption's end) or ``security-stop`` (never a new
    attempt: PRIOR_END_SECURITY_STOP); END_CAUSE_INVALID otherwise. Only for an end record that is unclassified
    (END_CAUSE_NOT_APPLICABLE for no end record or a classified one); the same cause again returns it, another is
    END_CAUSE_CONFLICT."""
    if cause not in END_CAUSES:
        raise _refused('END_CAUSE_INVALID', f'the cause must be one of {", ".join(END_CAUSES)}')
    if integration_store.get(operation_key) is None or integration_store.attempt_identity(operation_key) is None:
        raise _refused('RESERVATION_INVALID', f'no dispatch reservation under {operation_key!r}')
    attempt_id = store.attempt_id_for(operation_key)
    ended = end_record(integration_store, attempt_id)
    if ended is None or ended.get('classification') != UNCLASSIFIED:
        raise _refused('END_CAUSE_NOT_APPLICABLE', f'attempt {attempt_id} has no unclassified end record'
                       + ('' if ended is None else f' (it ended {ended.get("classification")})'))
    key = END_CAUSE_KEY.format(attempt_id=attempt_id)
    intent = {'format': END_CAUSE_FORMAT, 'operationKey': operation_key, 'attemptId': attempt_id,
              'conversationId': store.conversation_id_for(operation_key), 'cause': cause,
              'classification': INTERRUPTION if cause == END_CAUSE_INTERRUPTION else NON_RETRYABLE,
              'endRecord': END_KEY.format(attempt_id=attempt_id)}
    _write_cause(integration_store, key, intent, actor, 'END_CAUSE_CONFLICT')
    return end_cause_record(integration_store, attempt_id)


# ---------------------------------------------------------------------------
# The admission of a new attempt for the same task

@dataclass
class Admission:
    """What a new attempt was admitted on: the fingerprints the provider refused (each ended attempt whose cause is
    token-refused) and the token fingerprint the newest entry receipt holds. ``check_token`` refuses a token read
    that is a refused one, or not the receipt's (NATIVE_TOKEN_NOT_REPLACED)."""
    refused: tuple = ()
    expected: str | None = None
    prior: list = field(default_factory=list)

    def check_token(self, held) -> None:
        if not self.refused:
            return
        fingerprint = getattr(held, 'fingerprint', None)
        if fingerprint in self.refused or fingerprint != self.expected:
            raise _refused('NATIVE_TOKEN_NOT_REPLACED', 'the native token read is a token the provider refused, or '
                           'not the newest entry receipt\'s', token_fingerprint=fingerprint)


def entry_receipts(integration_store) -> list[tuple[int, str]]:
    """The confirmed native-token entry receipts (the Owner's entry command, E-05.9), as (event id of the
    confirmation, the token fingerprint it holds), oldest first. Fingerprints only."""
    shape = di._native_module().FINGERPRINT_SHAPE
    out = []
    for held in integration_store.attempts(['confirmed']):
        if not held.operation_key.startswith(ENTRY_RECEIPT_PREFIX):
            continue
        intent = _loads(held.intent_json)
        if not isinstance(intent, dict) or intent.get('format') != ENTRY_RECEIPT_FORMAT \
                or intent.get('entry') != di._native_module().ENTRY:
            continue
        detail = _detail(integration_store, held.operation_key, 'confirmed')
        fingerprint = detail.get('fingerprint_after') if isinstance(detail, dict) else None
        event = _event_id(integration_store, held.operation_key, 'confirmed')
        if isinstance(fingerprint, str) and shape.fullmatch(fingerprint) and event is not None:
            out.append((event, fingerprint))
    return sorted(out)


def admit_new_attempt(integration_store, resolved, *, transport, read_artifact) -> Admission:
    """The admission rule of a new attempt for the same task (the module docstring), before the reservation. An
    attempt with no earlier native conversation on its triple is admitted with no call."""
    identity = resolved.attempt_identity()
    prior = []
    for claim in integration_store.claims(identity.work_id, identity.design_revision, identity.stage):
        held = integration_store.get(claim.operation_key)
        if claim.identity.ordinal >= identity.ordinal or held is None or held.state != 'confirmed':
            continue   # failed: no conversation was created; live: the store's claim rule refuses the reservation
        if native_fingerprint(integration_store, claim.operation_key) is None:
            continue   # not a native D1 conversation: another stage's or profile's rule
        prior.append(claim)
    if not prior:
        return Admission()
    ended = []
    for claim in prior:
        record = end_record(integration_store, claim.attempt_id)
        if record is None:
            raise _refused('PRIOR_ATTEMPT_NOT_ENDED', f'attempt {claim.attempt_id} (ordinal {claim.identity.ordinal}) '
                           'has no end record', attempt_id=claim.attempt_id)
        ended.append((claim, record))
    effective = {claim.operation_key: effective_classification(integration_store, record) for claim, record in ended}
    for claim, record in ended:
        if effective[claim.operation_key] == NON_RETRYABLE:
            raise _refused('PRIOR_END_SECURITY_STOP', f'attempt {claim.attempt_id} ended non-retryable '
                           f'({", ".join(record.get("causes") or ["security-stop, recorded by the engineering manager"])}): a '
                           'security stop', attempt_id=claim.attempt_id)
    for claim, record in ended:
        if effective[claim.operation_key] not in (INTERRUPTION, AUTH_REFUSAL) \
                or record.get('conversationStopped') is not True:
            raise _refused('PRIOR_END_UNCLASSIFIED', f'attempt {claim.attempt_id} ended {record.get("classification")} '
                           'and the engineering manager has not classified it (record-end-cause)',
                           attempt_id=claim.attempt_id)
    client = None
    for claim, record in ended:
        if client is None:
            client = _client(resolved, transport)(read_artifact)
        observed = runtime_status(client, record['conversationId'], 'PRIOR_CONVERSATION_UNOBSERVED')
        if observed not in (None, STOPPED):
            raise _refused('PRIOR_CONVERSATION_RUNNING', f'the conversation of attempt {claim.attempt_id} is '
                           f'{observed!r}', attempt_id=claim.attempt_id, runtime_status=observed)
    refused, since = [], None
    for claim, record in ended:
        if record['classification'] != AUTH_REFUSAL:
            continue
        cause = cause_record(integration_store, claim.attempt_id)
        if cause is None:
            raise _refused('PRIOR_AUTH_CAUSE_UNRECORDED', f'attempt {claim.attempt_id} ended on an authentication '
                           'refusal and its cause is not recorded', attempt_id=claim.attempt_id)
        if cause.get('tokenRefused') is True:
            refused.append(cause.get('refusedFingerprint'))
            dispatched = _event_id(integration_store, claim.operation_key, 'dispatched')
            since = dispatched if since is None else max(since, dispatched)
    if not refused:
        return Admission(prior=[c.operation_key for c, _ in ended])
    receipts = entry_receipts(integration_store)
    newest = receipts[-1] if receipts else None
    if newest is None or newest[0] <= since or newest[1] in refused:
        raise _refused('PRIOR_AUTH_TOKEN_NOT_REPLACED', 'the provider refused the native token and no newer entry '
                       'receipt holds another token', refused=sorted(f for f in refused if f))
    return Admission(refused=tuple(refused), expected=newest[1], prior=[c.operation_key for c, _ in ended])


# ---------------------------------------------------------------------------
# Command line: the engineering manager's cause record

def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='The engineering manager\'s cause records of an ended attempt: an '
                                                 'authentication refusal\'s cause, an unclassified end\'s '
                                                 'classification (plan leaf E-05.8).')
    sub = parser.add_subparsers(dest='command', required=True)
    record = sub.add_parser('record-auth-cause', help='record the cause of an attempt\'s authentication refusal')
    record.add_argument('--store', required=True, help='the integration store (integration.sqlite)')
    record.add_argument('--operation-key', required=True, help='the ended attempt\'s operation key')
    record.add_argument('--cause', required=True, choices=AUTH_CAUSES)
    record.add_argument('--actor', default='engineering-manager')
    end = sub.add_parser('record-end-cause', help='classify an attempt\'s unclassified end')
    end.add_argument('--store', required=True, help='the integration store (integration.sqlite)')
    end.add_argument('--operation-key', required=True, help='the ended attempt\'s operation key')
    end.add_argument('--cause', required=True, choices=END_CAUSES)
    end.add_argument('--actor', default='engineering-manager')
    args = parser.parse_args(argv)
    write = record_auth_cause if args.command == 'record-auth-cause' else record_end_cause
    path = Path(args.store)
    if not path.is_file():
        print(f'REFUSED STORE_MISSING: {path} is not a file', file=sys.stderr)
        return 2
    opened = store.open_store(path)
    try:
        result = write(opened, args.operation_key, cause=args.cause, actor=args.actor)
    except DispatchRefused as exc:
        print(f'REFUSED {exc.code}: {exc.detail}', file=sys.stderr)
        return 1
    finally:
        opened.close()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
