"""Tests for the end of a provider-interrupted native attempt and the admission of a new attempt for the same task
(plan leaf E-05.8, decision 0023), offline.

Run from the repository root:

    python -I -B -m unittest discover -s integrations/dispatch/tests -p test_attempt_end.py -v

The proof, clause by clause:

* Each provider refusal (authentication, a usage or rate limit, overload), a cut-off stream and a lost path, as the
  pinned SDK records them in the conversation's events, is recorded as an interruption (an authentication refusal as
  one that needs the Owner); every containment, credential or unexpected-egress stop of the dispatcher's own records
  is non-retryable (``Classification``).
* The classification is taken from the conversation's recorded status and events and the dispatcher's own records,
  never from an exit or HTTP status alone: an Agent Server status, a number in an agent message, the SDK's own
  classification object or a status number in a non-error event classifies nothing (``NeverFromAStatusAlone``).
* The end: the runtime stopped and observed stopped; one end record (attempt, conversation, classification, the
  surfaced codes and statuses, the fingerprint only) written durably in the integration store; the reservation
  receipt and the task's Backlog.md and OpenSpec records unchanged; no result handed on (``CleanEnd``); its
  refusals (``EndRefusals``).
* Repeat-safety: every step repeated, and a crash after the journal began, after the runtime stopped and after the
  end record was written, converge on one end record (``RepeatSafety``).
* A new attempt (the next ordinal, same work item, design revision and stage, a new conversation) only after an
  interruption's end record with the conversation stopped; refused with a stable code while the earlier attempt has
  no end record or its conversation runs, after a non-retryable end (a security stop) and after an unclassified one
  (``NewAttempt``).
* An authentication refusal needs the Owner: no new attempt until the engineering manager records its cause, and
  where the provider refused the token, until a newer native-token entry receipt (the Owner's entry command, E-05.9)
  holds another token, which is then the token read; never an automatic retry (``AuthenticationRefusal``,
  ``CauseCommand``).
* The token is never delivered again to an existing conversation or attempt, and no record, report or log carries
  it, only its fingerprint (``TokenNeverAgain``).

The Agent Server is a fake of the pinned 1.60.1 routes the end uses (its ConversationInfo, the event search with
its pages, the runtime stop and the runtime status), on the E-05.9 native fixture. The conversation's events are
built in the shapes the pinned SDK writes (``ConversationErrorEvent`` with its code, detail and classification) and
the details in the texts the pinned CLI and adapter produce (the E-05.8 determination record). The credential
provider is in memory; the tokens are synthetic. No broker, guest, provider, model or credential store is used.
"""
from pathlib import Path
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import sys
import unittest
import uuid
from unittest import mock

CATEGORY = 'integration'

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]


def _load(name, path):
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


native_tests = _load('test_native_d1_stage', HERE / 'test_native_d1_stage.py')
NF, cc, di, store_mod, NS = native_tests, native_tests.cc, native_tests.di, native_tests.store_mod, native_tests.NS
AE = di._attempt_end()
NT = di._native_module()
TOKEN, NEW_TOKEN = native_tests.TOKEN, NS.token('E-05.8 replacement token')

# The pinned SDK's ConversationErrorEvent codes, and details as acp_agent.py _acp_error_detail renders the adapter's
# RequestError (message: the CLI's API error text; data: {"errorKind": <the CLI's assistant error kind>}).
DATA = '{{"errorKind": "{}"}}'


def detail(code, message, kind=None):
    return f'[{code}] {message}' + (f': {DATA.format(kind)}' if kind else '')


def error_event(code, text, sdk_kind='config', source='agent'):
    return {'kind': 'ConversationErrorEvent', 'id': str(uuid.uuid4()), 'timestamp': '2026-11-14T00:00:00',
            'source': source, 'code': code, 'detail': text,
            'classification': {'kind': sdk_kind, 'retryable': False, 'user_action': 'settings'}}


def message_event(text, source='agent'):
    return {'kind': 'MessageEvent', 'id': str(uuid.uuid4()), 'timestamp': '2026-11-14T00:00:00', 'source': source,
            'llm_message': {'role': 'assistant', 'content': [{'type': 'text', 'text': text}]}}


SURFACED = {
    # an authentication refusal: the adapter's authRequired (-32000), and a 401 the SDK reads as one (-32603)
    'auth-required': (error_event('ACPAuthRequired', detail(-32000, 'Authentication required'), 'auth'),
                      AE.AUTH_REFUSAL, ['authentication']),
    'oauth-expired': (error_event('ACPAuthRequired', detail(
        -32603, 'Failed to authenticate. API Error: 401 {"type":"error","error":{"type":"authentication_error",'
        '"message":"OAuth token has expired."}}', 'authentication_failed'), 'auth'), AE.AUTH_REFUSAL,
        ['authentication']),
    'org-not-allowed': (error_event('ACPPromptError', detail(-32603, 'API Error: 403 OAuth authentication is '
                                                             'currently not allowed for this organization',
                                                             'oauth_org_not_allowed')), AE.AUTH_REFUSAL,
                        ['authentication']),
    'auth-at-start': (error_event('ACPAuthRequired', detail(-32603, 'Invalid API key · Please run /login'), 'auth'),
                      AE.AUTH_REFUSAL, ['authentication']),
    # a usage or rate limit (the SDK classifies ACPPromptError as config, whatever its detail)
    'rate-limit': (error_event('ACPPromptError', detail(-32603, 'API Error: Server is temporarily limiting requests '
                                                        '(not your usage limit) · Rate limited', 'rate_limit')),
                   AE.INTERRUPTION, ['usage-limit']),
    'usage-limit': (error_event('ACPPromptError', detail(-32603, "You've hit your session limit · resets 3pm",
                                                         'rate_limit')), AE.INTERRUPTION, ['usage-limit']),
    'billing': (error_event('ACPPromptError', detail(-32603, 'Credit balance is too low', 'billing_error')),
                AE.INTERRUPTION, ['usage-limit']),
    # overload
    'repeated-529': (error_event('ACPPromptError', detail(-32603, 'API Error: Repeated 529 Overloaded errors. The API '
                                                          'is at capacity — this is usually temporary. Try again in a '
                                                          'moment.', 'server_error')), AE.INTERRUPTION, ['overload']),
    'server-5xx': (error_event('ACPPromptError', detail(-32603, 'API Error: 503 Service Unavailable. This is a '
                                                        'server-side issue, usually temporary — try again in a '
                                                        'moment.', 'server_error')), AE.INTERRUPTION, ['overload']),
    # a stream the provider cut off
    'connection-reset': (error_event('ACPPromptError', detail(-32603, 'API Error: Connection to the API was lost '
                                                              '(ECONNRESET). This is usually temporary — try again.',
                                                              'server_error')), AE.INTERRUPTION, ['stream-cut']),
    'request-timeout': (error_event('ACPPromptError', detail(-32603, 'Request timed out', 'server_error')),
                        AE.INTERRUPTION, ['stream-cut']),
    # a lost path to the provider (the tunnel or the forward refused)
    'proxy-refused': (error_event('ACPPromptError', detail(-32603, 'API Error: Connection to the API was lost '
                                                           '(ECONNREFUSED). This is usually temporary — try again.',
                                                           'server_error')), AE.INTERRUPTION, ['path-lost']),
    'proxy-tunnel': (error_event('ACPPromptError', detail(-32603, 'API Error: Unable to connect to API '
                                                          '(ERR_PROXY_TUNNEL)', 'server_error')), AE.INTERRUPTION,
                     ['path-lost']),
}
STOPS = {'containment-stop': 'containment', 'credential-stop': 'credential', 'egress-stop': 'unexpected-egress'}


def record(kind, code='STOP_OBSERVED', ref='evidence:test/1'):
    return {'kind': kind, 'code': code, 'ref': ref}


class ConversationServer(cc.FakeAgentServer):
    """The pinned Agent Server, faked: server_info and the create as E-01.3.1's fake, and for each created
    conversation its ConversationInfo, its events (the event search, PAGE events a page), the runtime stop and the
    runtime status. ``fail`` maps (method, route kind) to an answer or an exception for the next calls."""

    PAGE = 2

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.conversations, self.fail = {}, {}

    def conversation(self, cid=None):
        return self.conversations[cid or next(iter(self.conversations))]

    def set(self, cid=None, status=None, events=None, runtime=None):
        held = self.conversation(cid)
        if status is not None:
            held['execution_status'] = status
        if events is not None:
            held['events'] = list(events)
        if runtime is not None:
            held['runtime'] = runtime

    def __call__(self, method, path, body):
        if (method, path) == cc.CREATE:
            answer = super().__call__(method, path, body)
            if answer.get('status') in (200, 201):
                self.conversations.setdefault(body['conversation_id'], {
                    'execution_status': 'running', 'events': [], 'runtime': 'available'})
            return answer
        if (method, path) == cc.INFO:
            return super().__call__(method, path, body)
        self.calls.append((method, path, copy.deepcopy(body)))
        route, _, query = path.partition('?')
        parts = route.split('/')
        assert parts[:3] == ['', 'api', 'conversations'], path
        cid, tail = parts[3], '/'.join(parts[4:])
        kind = {'': 'info', 'events/search': 'events', 'runtime': 'runtime'}[tail]
        failure = self.fail.get((method, kind))
        if isinstance(failure, BaseException):
            raise failure
        if failure is not None:
            return copy.deepcopy(failure)
        held = self.conversations.get(cid)
        if held is None:
            return {'status': 404, 'body': {'detail': 'Conversation not found'}}
        if (method, kind) == ('GET', 'info'):
            return {'status': 200, 'body': {'id': cid, 'execution_status': held['execution_status']}}
        if (method, kind) == ('GET', 'events'):
            start = 0
            if query:
                name, _, page = query.partition('=')
                assert name == 'page_id', query
                start = [e['id'] for e in held['events']].index(page)
            items = held['events'][start:start + self.PAGE]
            following = held['events'][start + self.PAGE]['id'] if start + self.PAGE < len(held['events']) else None
            return {'status': 200, 'body': {'items': copy.deepcopy(items), 'next_page_id': following}}
        if (method, kind) == ('DELETE', 'runtime'):
            held['runtime'] = 'missing'
            return {'status': 204, 'body': None}
        if (method, kind) == ('GET', 'runtime'):
            return {'status': 200, 'body': {'runtime_status': held['runtime'], 'can_resume': True}}
        raise AssertionError(f'unexpected call {method} {path}')

    def calls_to(self, cid):
        return [c for c in self.calls if f'/api/conversations/{cid}' in c[1]]


class Crash(BaseException):
    """A process dying at a point the test chooses (never caught as an Exception)."""


class EndFixture(NF.NativeFixture):
    def setUp(self):
        super().setUp()
        self.server = ConversationServer()
        self.manifest = self.approve_native()

    def dispatch_native(self, provider=None):
        return self.run_native(self.server, provider=provider, manifest=self.manifest)

    def interrupted(self, *events, status='error', provider=None):
        """A confirmed native attempt whose conversation ended with EVENTS (an agent message first)."""
        result = self.dispatch_native(provider)
        self.server.set(result.conversation_id, status=status,
                        events=[message_event('working on it', 'user'), *events])
        return result

    def end(self, result, trigger=AE.CONVERSATION_ENDED, records=(), transport=None):
        return AE.end_interrupted_attempt(self.store, result.operation_key, transport=transport or self.server,
                                          actor='e-05.8-test', trigger=trigger, dispatcher_records=list(records),
                                          read_artifact=self.read_artifact)

    def end_keys(self):
        return [a.operation_key for a in self.store.attempts() if a.operation_key.endswith('/end')]

    def refused_end(self, code, result, **kwargs):
        with self.assertRaises(di.DispatchRefused) as caught:
            self.end(result, **kwargs)
        self.assertEqual(caught.exception.code, code, caught.exception.detail)
        self.assertIn(code, di.REFUSALS)
        return caught.exception

    def refused_dispatch(self, code, provider=None):
        before = [a.operation_key for a in self.store.attempts()]
        creates = len(self.server.creates)
        reads = list((provider or self.provider).reads)
        with self.assertRaises(di.DispatchRefused) as caught:
            self.dispatch_native(provider)
        self.assertEqual(caught.exception.code, code, caught.exception.detail)
        self.assertIn(code, di.REFUSALS)
        self.assertEqual(len(self.server.creates), creates, 'a refused new attempt sends no create')
        return caught.exception, before, reads

    def assertNothingReserved(self, before):
        self.assertEqual([a.operation_key for a in self.store.attempts()], before)

    def ordinal(self, key):
        return self.store.attempt_identity(key).identity.ordinal

    def ended_on_auth(self):
        first = self.interrupted(SURFACED['oauth-expired'][0])
        self.assertEqual(self.end(first)['classification'], AE.AUTH_REFUSAL)
        return first


class Classification(EndFixture):
    def test_each_surfaced_refusal_cut_and_lost_path_is_an_interruption(self):
        for name, (event, classification, causes) in SURFACED.items():
            with self.subTest(name):
                verdict = AE.classify('error', [message_event('hi'), event], [])
                self.assertEqual((verdict['classification'], verdict['causes']), (classification, causes))
                self.assertTrue(verdict['retryable'])
                self.assertEqual(verdict['needsOwner'], classification == AE.AUTH_REFUSAL)
                self.assertFalse(verdict['securityStop'])
        verdict = AE.classify('running', [], [record('provider-path-lost', 'FORWARD_LOST')])
        self.assertEqual((verdict['classification'], verdict['causes']), (AE.INTERRUPTION, ['path-lost']))

    def test_every_containment_credential_or_egress_stop_is_non_retryable(self):
        for kind, cause in STOPS.items():
            for event, _, _ in [(None, None, None), *SURFACED.values()]:
                with self.subTest(kind=kind, event=event and event['detail'][:30]):
                    verdict = AE.classify('error', [] if event is None else [event], [record(kind)])
                    self.assertEqual((verdict['classification'], verdict['causes']), (AE.NON_RETRYABLE, [cause]))
                    self.assertEqual((verdict['retryable'], verdict['securityStop']), (False, True))

    def test_an_authentication_refusal_outranks_another_interruption(self):
        verdict = AE.classify('error', [SURFACED['rate-limit'][0], SURFACED['oauth-expired'][0]], [])
        self.assertEqual(verdict['classification'], AE.AUTH_REFUSAL)

    def test_the_surfaced_codes_and_statuses_are_recorded_without_the_detail(self):
        event = SURFACED['oauth-expired'][0]
        [signal] = AE.classify('error', [event], [])['surfaced']['errorEvents']
        self.assertEqual(signal, {'eventId': event['id'], 'source': 'agent', 'code': 'ACPAuthRequired',
                                  'errorKind': 'authentication_failed', 'connectionCode': None, 'statuses': ['401'],
                                  'sdkKind': 'auth', 'cause': 'authentication'})
        self.assertNotIn('OAuth token has expired', json.dumps(signal))
        [signal] = AE.classify('error', [SURFACED['proxy-refused'][0]], [])['surfaced']['errorEvents']
        self.assertEqual((signal['connectionCode'], signal['cause']), ('ECONNREFUSED', 'path-lost'))

    def test_the_dispatcher_records_are_of_their_grammar(self):
        for bad in ([{'kind': 'containment-stop', 'code': 'X'}], [record('reboot')], [record('egress-stop', 'lower')],
                    [record('egress-stop', ref='has space')], [{**record('egress-stop'), 'extra': 1}], 'x'):
            with self.subTest(bad=bad), self.assertRaises(di.DispatchRefused) as caught:
                AE.check_records(bad)
            self.assertEqual(caught.exception.code, 'DISPATCHER_RECORD_INVALID')

    def test_the_cli_connection_code_sets_are_disjoint(self):
        self.assertFalse(AE.STREAM_CUT_CODES & AE.PATH_LOST_CODES)


class NeverFromAStatusAlone(EndFixture):
    def test_nothing_but_an_error_event_or_a_dispatcher_record_classifies(self):
        cases = {
            'error status, no event': [],
            'an agent message naming 429 and 401': [message_event('API Error: 429 rate limit; 401 unauthorized')],
            'a user message': [message_event('Connection to the API was lost (ECONNRESET)', 'user')],
            'an observation with a status': [{'kind': 'ObservationEvent', 'id': 'o1', 'source': 'environment',
                                              'observation': {'content': 'HTTP 503 overloaded'}}],
            'the SDK classification alone': [error_event('KeyError', 'boom', 'rate_limit')],
            'a status number without an error kind': [error_event('ACPPromptError',
                                                                  detail(-32603, 'API Error: 529 overloaded'))],
            'the adapter process died': [error_event('ACPPromptError', detail(
                -32603, 'The Claude Agent process exited unexpectedly. Please start a new session.'))],
            'an invalid request': [error_event('ACPPromptError', detail(-32603, 'API Error: 400 bad', 'invalid_request'))],
            'a content-policy refusal': [error_event('UsagePolicyRefusal', 'usage policy', 'config')],
            'an SSL failure through the tunnel': [error_event('ACPPromptError', detail(
                -32603, 'API Error: Unable to connect to API: SSL certificate verification failed', 'server_error'))],
        }
        for name, events in cases.items():
            with self.subTest(name):
                self.assertEqual(AE.classify('error', events, [])['classification'], AE.UNCLASSIFIED)

    def test_an_agent_server_http_status_is_never_a_classification(self):
        for status in (401, 403, 429, 500, 503, 529):
            for kind in ('info', 'events'):
                with self.subTest(status=status, kind=kind):
                    result = self.interrupted(SURFACED['rate-limit'][0])
                    self.server.fail = {('GET', kind): {'status': status, 'body': {'detail': 'x'}}}
                    self.refused_end('CONVERSATION_UNOBSERVED', result)
                    self.assertIsNone(self.store.get(AE.END_KEY.format(attempt_id=result.attempt_id)))
                    self.assertEqual([c for c in self.server.calls_to(result.conversation_id) if c[0] == 'DELETE'], [])
                    self.server.fail = {}
                    self.end(result)   # ended, so that the next attempt may be dispatched
        self.server.fail = {}

    def test_no_answer_is_never_a_classification(self):
        result = self.interrupted(SURFACED['proxy-refused'][0])
        self.server.fail = {('GET', 'events'): ConnectionError('lost')}
        self.refused_end('CONVERSATION_UNOBSERVED', result)
        self.assertEqual(self.end_keys(), [])


class CleanEnd(EndFixture):
    def test_the_runtime_is_stopped_observed_stopped_and_one_end_record_is_written(self):
        event = SURFACED['rate-limit'][0]
        result = self.interrupted(*[message_event(f'step {n}') for n in range(5)], event)
        reservation, events = self.store.get(result.operation_key), self.store.events(result.operation_key)
        reads = self.sources['demo-app'].reads
        design = self.tree_digest(self.design_repo)
        calls = len(self.server.calls)
        ended = self.end(result)
        made = self.server.calls[calls:]
        # the runtime: read, stopped (DELETE), observed missing (GET runtime), read again; every call bodyless
        cid = result.conversation_id
        self.assertEqual([(m, p.split('?')[0]) for m, p, _ in made],
                         [('GET', f'/api/conversations/{cid}')] + [('GET', f'/api/conversations/{cid}/events/search')] * 4
                         + [('DELETE', f'/api/conversations/{cid}/runtime'), ('GET', f'/api/conversations/{cid}/runtime'),
                            ('GET', f'/api/conversations/{cid}')] + [('GET', f'/api/conversations/{cid}/events/search')] * 4)
        self.assertEqual([b for _, _, b in made], [None] * len(made))
        self.assertEqual(self.server.conversation(cid)['runtime'], 'missing')
        # the end record
        identity = self.store.attempt_identity(result.operation_key).identity
        self.assertEqual(ended['format'], AE.END_FORMAT)
        self.assertEqual({k: ended[k] for k in ('operationKey', 'attemptId', 'conversationId', 'executionRef', 'workId',
                                                'designRevision', 'stage', 'ordinal', 'trigger', 'classification',
                                                'causes', 'retryable', 'needsOwner', 'securityStop',
                                                'conversationStopped', 'resultHandedOn', 'tokenFingerprint')},
                         {'operationKey': result.operation_key, 'attemptId': result.attempt_id, 'conversationId': cid,
                          'executionRef': result.execution_ref, 'workId': identity.work_id,
                          'designRevision': identity.design_revision, 'stage': identity.stage, 'ordinal': 1,
                          'trigger': 'conversation-ended', 'classification': AE.INTERRUPTION,
                          'causes': ['usage-limit'], 'retryable': True, 'needsOwner': False, 'securityStop': False,
                          'conversationStopped': True, 'resultHandedOn': False,
                          'tokenFingerprint': NT.fingerprint(TOKEN)})
        self.assertEqual(ended['surfaced']['executionStatus'], 'error')
        self.assertEqual(ended['surfaced']['runtimeStatus'], 'missing')
        self.assertEqual([s['eventId'] for s in ended['surfaced']['errorEvents']], [event['id']])
        self.assertEqual(ended['surfaced']['errorEvents'][0]['errorKind'], 'rate_limit')
        # durably: the store file read through a new connection holds it, once
        self.assertEqual(self.end_keys(), [AE.END_KEY.format(attempt_id=result.attempt_id)])
        again = store_mod.open_store(self.case / 'integration.sqlite')
        try:
            self.assertEqual(AE.end_record(again, result.attempt_id), ended)
        finally:
            again.close()
        # the reservation receipt, Backlog.md and OpenSpec kept unchanged; no result handed on
        self.assertEqual((self.store.get(result.operation_key), self.store.events(result.operation_key)),
                         (reservation, events))
        self.assertEqual(self.sources['demo-app'].reads, reads)
        self.assertEqual(self.tree_digest(self.design_repo), design)
        for method, path, _ in made:
            self.assertNotIn('agent_final_response', path)
            self.assertNotIn('workspace', path)
            self.assertNotIn('/file', path)

    def test_an_attempt_the_dispatcher_stops_is_ended_while_its_conversation_runs(self):
        result = self.interrupted(SURFACED['connection-reset'][0], status='running')
        ended = self.end(result, trigger=AE.ATTEMPT_STOPPED, records=[record('provider-path-lost', 'TUNNEL_DOWN')])
        self.assertEqual((ended['trigger'], ended['classification'], ended['causes']),
                         ('attempt-stopped', AE.INTERRUPTION, ['path-lost', 'stream-cut']))
        self.assertEqual(ended['surfaced']['dispatcherRecords'], [record('provider-path-lost', 'TUNNEL_DOWN')])
        self.assertEqual(self.server.conversation()['runtime'], 'missing')

    def test_each_classification_is_recorded(self):
        cases = [((SURFACED['oauth-expired'][0],), (), AE.AUTH_REFUSAL),
                 ((SURFACED['repeated-529'][0],), (), AE.INTERRUPTION),
                 ((SURFACED['rate-limit'][0],), (record('credential-stop', 'TOKEN_FOUND_OUTBOUND'),), AE.NON_RETRYABLE),
                 ((), (), AE.UNCLASSIFIED)]
        for events, records, classification in cases:
            with self.subTest(classification):
                self.setUp()
                result = self.interrupted(*events)
                ended = self.end(result, records=records)
                self.assertEqual(ended['classification'], classification)
                self.assertEqual(ended['needsOwner'], classification == AE.AUTH_REFUSAL)
                self.assertEqual(ended['securityStop'], classification == AE.NON_RETRYABLE)

    @staticmethod
    def tree_digest(root):
        digest = hashlib.sha256()
        for path in sorted(p for p in Path(root).rglob('*') if p.is_file()):
            digest.update(str(path.relative_to(root)).encode() + b'\0' + path.read_bytes())
        return digest.hexdigest()


class EndRefusals(EndFixture):
    def test_a_running_conversation_has_not_ended(self):
        result = self.interrupted(SURFACED['rate-limit'][0], status='running')
        self.refused_end('CONVERSATION_STILL_RUNNING', result)
        self.assertEqual((self.end_keys(), [c for c in self.server.calls if c[0] == 'DELETE']), ([], []))

    def test_a_finished_conversation_is_the_result_path_s(self):
        result = self.interrupted(SURFACED['rate-limit'][0], status='finished')
        self.refused_end('ATTEMPT_NOT_INTERRUPTED', result)
        self.assertEqual((self.end_keys(), [c for c in self.server.calls if c[0] == 'DELETE']), ([], []))
        # a security stop of the dispatcher's still ends it
        self.assertEqual(self.end(result, records=[record('egress-stop', 'TUNNEL_REFUSED_HOST')])['classification'],
                         AE.NON_RETRYABLE)

    def test_only_a_confirmed_native_attempt_is_ended(self):
        with self.assertRaises(di.DispatchRefused) as caught:
            self.run_native(self.server, provider=NS.ObservedProvider({}), manifest=self.manifest)
        failed = self.store.attempts(['failed'])[0]
        with self.assertRaises(di.DispatchRefused) as caught:
            AE.end_interrupted_attempt(self.store, failed.operation_key, transport=self.server, actor='t',
                                       trigger=AE.CONVERSATION_ENDED, read_artifact=self.read_artifact)
        self.assertEqual(caught.exception.code, 'ATTEMPT_NOT_CONFIRMED')
        with self.assertRaises(di.DispatchRefused) as caught:
            AE.end_interrupted_attempt(self.store, 'attempt/v1/NOPE', transport=self.server, actor='t',
                                       trigger=AE.CONVERSATION_ENDED, read_artifact=self.read_artifact)
        self.assertEqual(caught.exception.code, 'RESERVATION_INVALID')
        result = self.interrupted(SURFACED['rate-limit'][0])
        self.store.reserve(di.GRANT_JOURNAL_KEY.format(attempt_id=result.attempt_id), {'format': 'x'}, actor='t')
        self.refused_end('ATTEMPT_PROFILE_BROKERED', result)
        with self.assertRaises(ValueError):
            self.end(result, trigger='done')
        self.refused_end('DISPATCHER_RECORD_INVALID', result, records=[record('nope')])

    def test_a_runtime_not_stopped_or_not_observed_stopped_records_no_end(self):
        cases = {'stop answered 502': {('DELETE', 'runtime'): {'status': 502, 'body': {}}},
                 'stop unanswered': {('DELETE', 'runtime'): ConnectionError('lost')},
                 'still available': {('GET', 'runtime'): {'status': 200, 'body': {'runtime_status': 'available'}}},
                 'runtime error': {('GET', 'runtime'): {'status': 200, 'body': {'runtime_status': 'error'}}}}
        for name, fail in cases.items():
            with self.subTest(name):
                self.setUp()
                result = self.interrupted(SURFACED['rate-limit'][0])
                self.server.fail = fail
                self.refused_end('RUNTIME_NOT_STOPPED', result)
                key = AE.END_KEY.format(attempt_id=result.attempt_id)
                self.assertEqual(self.store.get(key).state, 'dispatched')   # begun, not recorded
                self.assertIsNone(AE.end_record(self.store, result.attempt_id))

    def test_an_unknown_conversation_is_ended_absent_and_unclassified(self):
        """S4 (the review's P4): a conversation the server no longer knows is ended, absent and unclassified, so
        that record-end-cause decides it; repeat-safe."""
        result = self.interrupted(SURFACED['rate-limit'][0])
        del self.server.conversations[result.conversation_id]
        ended = self.end(result, records=[record('provider-path-lost', 'TUNNEL_DOWN')])
        self.assertEqual((ended['classification'], ended['surfaced']['runtimeStatus'], ended['conversationStopped']),
                         (AE.UNCLASSIFIED, AE.ABSENT, True))
        self.assertEqual(ended['surfaced']['dispatcherRecords'], [record('provider-path-lost', 'TUNNEL_DOWN')])
        self.assertEqual(self.end(result), ended)
        self.refused_dispatch('PRIOR_END_UNCLASSIFIED')
        AE.record_end_cause(self.store, result.operation_key, cause=AE.END_CAUSE_INTERRUPTION, actor='em')
        self.assertEqual(self.ordinal(self.dispatch_native().operation_key), 2)

    def test_an_unknown_conversation_with_a_security_stop_is_non_retryable(self):
        result = self.interrupted(SURFACED['rate-limit'][0])
        del self.server.conversations[result.conversation_id]
        self.assertEqual(self.end(result, records=[record('egress-stop')])['classification'], AE.NON_RETRYABLE)

    def test_a_conversation_lost_after_the_stop_is_ended_absent(self):
        result = self.interrupted(SURFACED['rate-limit'][0])
        real = self.server.__call__

        def losing(method, path, body):
            answer = real(method, path, body)
            if method == 'DELETE':
                self.server.conversations.pop(result.conversation_id, None)
            return answer
        ended = self.end(result, transport=losing)
        self.assertEqual((ended['classification'], ended['surfaced']['runtimeStatus']), (AE.UNCLASSIFIED, AE.ABSENT))


class RepeatSafety(EndFixture):
    def assertOneEnd(self, result):
        self.assertEqual(self.end_keys(), [AE.END_KEY.format(attempt_id=result.attempt_id)])
        key = AE.END_KEY.format(attempt_id=result.attempt_id)
        self.assertEqual([e.to_state for e in self.store.events(key)], ['reserved', 'dispatched', 'confirmed'])

    def test_repeating_the_end_returns_its_one_record_with_no_call(self):
        result = self.interrupted(SURFACED['server-5xx'][0])
        first = self.end(result)
        calls = len(self.server.calls)
        for _ in range(3):
            self.assertEqual(self.end(result), first)
        self.assertEqual(len(self.server.calls), calls)
        self.assertOneEnd(result)

    def crash_at(self, result, *, when):
        """End RESULT with a Crash raised at WHEN: 'begun' (the journal reserved, not dispatched), 'stopped' (after
        the runtime stopped and was observed stopped) or 'recorded' (after the end record was committed)."""
        real_mark, real_stop = di._mark, AE.stop_runtime
        key = AE.END_KEY.format(attempt_id=result.attempt_id)

        def mark(integration_store, k, from_state, to_state, *args):
            if k == key and when == 'begun' and to_state == 'dispatched':
                raise Crash()
            real_mark(integration_store, k, from_state, to_state, *args)
            if k == key and when == 'recorded' and to_state == 'confirmed':
                raise Crash()

        def stop(client, cid):
            observed = real_stop(client, cid)
            if when == 'stopped':
                raise Crash()
            return observed
        with mock.patch.object(di, '_mark', mark), mock.patch.object(AE, 'stop_runtime', stop), \
                self.assertRaises(Crash):
            self.end(result)

    def test_a_crash_at_each_step_converges_on_one_end_record(self):
        for when, state in (('begun', 'reserved'), ('stopped', 'dispatched'), ('recorded', 'confirmed')):
            with self.subTest(when):
                self.setUp()
                result = self.interrupted(SURFACED['proxy-tunnel'][0])
                self.crash_at(result, when=when)
                key = AE.END_KEY.format(attempt_id=result.attempt_id)
                self.assertEqual(self.store.get(key).state, state)
                stops = len([c for c in self.server.calls if c[0] == 'DELETE'])
                self.assertEqual(stops, 0 if when == 'begun' else 1)
                ended = self.end(result)
                ended_again = self.end(result)
                self.assertEqual(ended, ended_again)
                self.assertEqual((ended['classification'], ended['causes']), (AE.INTERRUPTION, ['path-lost']))
                self.assertOneEnd(result)
                # the runtime stop is repeated when the end resumes before its record, never after it
                self.assertEqual(len([c for c in self.server.calls if c[0] == 'DELETE']),
                                 {'begun': 1, 'stopped': 2, 'recorded': 1}[when])

    def test_a_failed_stop_is_resumed_by_the_repeat(self):
        result = self.interrupted(SURFACED['rate-limit'][0])
        self.server.fail = {('DELETE', 'runtime'): ConnectionError('lost')}
        self.refused_end('RUNTIME_NOT_STOPPED', result)
        self.refused_end('RUNTIME_NOT_STOPPED', result)
        self.server.fail = {}
        self.assertEqual(self.end(result)['classification'], AE.INTERRUPTION)
        self.assertOneEnd(result)

    def test_an_end_resumes_only_as_it_began(self):
        result = self.interrupted(SURFACED['rate-limit'][0])
        self.crash_at(result, when='stopped')
        self.refused_end('ATTEMPT_END_CONFLICT', result, trigger=AE.ATTEMPT_STOPPED)
        self.refused_end('ATTEMPT_END_CONFLICT', result, records=[record('egress-stop')])
        self.assertEqual(self.end(result)['classification'], AE.INTERRUPTION)
        self.assertOneEnd(result)


class NewAttempt(EndFixture):
    def test_a_new_attempt_after_an_interruption_s_end_gets_the_next_ordinal_and_a_new_conversation(self):
        first = self.interrupted(SURFACED['connection-reset'][0])
        self.end(first)
        second = self.dispatch_native()
        a, b = (self.store.attempt_identity(r.operation_key).identity for r in (first, second))
        self.assertEqual((b.work_id, b.design_revision, b.stage, b.ordinal),
                         (a.work_id, a.design_revision, a.stage, a.ordinal + 1))
        self.assertNotEqual(second.conversation_id, first.conversation_id)
        [(_, _, body)] = [c for c in self.server.creates if c[2]['conversation_id'] == second.conversation_id]
        self.assertEqual(body['secrets']['CLAUDE_CODE_OAUTH_TOKEN']['value'], TOKEN)
        # the ended attempt's conversation was only observed (its runtime), never sent a body
        self.assertEqual([b for _, _, b in self.server.calls_to(first.conversation_id)],
                         [None] * len(self.server.calls_to(first.conversation_id)))
        # and a third after the second's end
        self.server.set(second.conversation_id, status='error', events=[SURFACED['repeated-529'][0]])
        self.end(second)
        self.assertEqual(self.ordinal(self.dispatch_native().operation_key), 3)

    def test_refused_while_the_earlier_attempt_has_no_end_record(self):
        self.interrupted(SURFACED['rate-limit'][0])
        _, before, reads = self.refused_dispatch('PRIOR_ATTEMPT_NOT_ENDED')
        self.assertNothingReserved(before)
        self.assertEqual(self.provider.reads, reads)   # the token is not even read

    def test_refused_while_the_earlier_conversation_runs(self):
        first = self.interrupted(SURFACED['rate-limit'][0])
        self.end(first)
        self.server.set(first.conversation_id, runtime='available')   # reprovisioned since its end
        _, before, _ = self.refused_dispatch('PRIOR_CONVERSATION_RUNNING')
        self.assertNothingReserved(before)
        self.server.set(first.conversation_id, runtime='starting')
        self.refused_dispatch('PRIOR_CONVERSATION_RUNNING')
        self.server.fail = {('GET', 'runtime'): ConnectionError('lost')}
        self.refused_dispatch('PRIOR_CONVERSATION_UNOBSERVED')
        self.server.fail = {}
        self.server.set(first.conversation_id, runtime='missing')
        self.assertEqual(self.ordinal(self.dispatch_native().operation_key), 2)

    def test_a_non_retryable_end_stops_the_leaf_as_a_security_stop(self):
        for kind in STOPS:
            with self.subTest(kind):
                self.setUp()
                first = self.interrupted(SURFACED['rate-limit'][0])
                self.end(first, records=[record(kind)])
                _, before, reads = self.refused_dispatch('PRIOR_END_SECURITY_STOP')
                self.assertNothingReserved(before)
                self.assertEqual(self.provider.reads, reads)

    def test_an_unclassified_end_admits_no_new_attempt(self):
        first = self.interrupted()
        self.assertEqual(self.end(first)['classification'], AE.UNCLASSIFIED)
        self.refused_dispatch('PRIOR_END_UNCLASSIFIED')

    def test_an_attempt_refused_before_its_create_needs_no_end(self):
        with self.assertRaises(di.DispatchRefused):
            self.run_native(self.server, provider=NS.ObservedProvider({}), manifest=self.manifest)
        self.assertEqual(self.ordinal(self.dispatch_native().operation_key), 2)


class AuthenticationRefusal(EndFixture):
    def enter(self, token):
        """The Owner's entry command (E-05.9, OA-31 (e)) with an in-memory console and provider, writing its
        aieh-credential-act/1 receipt into this test's integration store; the provider it wrote."""
        E = _load('aieh_native_token_entry', REPO / 'integrations' / 'credentials' / 'native_token_entry.py')
        entries = {}

        class Memory(E.credentials.contract.CredentialProvider):
            name = 'memory-fake'

            def get(self, name):
                return entries.get(name)

            def set(self, name, user, secret, comment=''):
                entries[name] = (user, secret)

            def delete(self, name):
                return entries.pop(name, None) is not None

        class Console:
            def interactive(self):
                return True

            def read_hidden(self, prompt):
                return token
        ctx = E.Context(provider=Memory, store=lambda: store_mod.open_store(self.case / 'integration.sqlite'),
                        console=Console(), out=io.StringIO(), err=io.StringIO())
        self.assertEqual(E.main(['enter'], ctx), 0, ctx.err.getvalue())
        return NS.ObservedProvider(entries)

    def cause(self, result, cause):
        return AE.record_auth_cause(self.store, result.operation_key, cause=cause, actor='engineering-manager')

    def test_never_an_automatic_retry_until_the_cause_is_recorded(self):
        first = self.ended_on_auth()
        _, before, reads = self.refused_dispatch('PRIOR_AUTH_CAUSE_UNRECORDED')
        self.assertNothingReserved(before)
        self.assertEqual(self.provider.reads, reads)
        recorded = self.cause(first, 'account-not-permitted')
        self.assertEqual((recorded['cause'], recorded['tokenRefused'], recorded['refusedFingerprint']),
                         ('account-not-permitted', False, None))
        self.assertEqual(self.ordinal(self.dispatch_native().operation_key), 2)   # the same token: not refused

    def test_a_refused_token_needs_a_newer_entry_holding_another_token(self):
        first = self.ended_on_auth()
        recorded = self.cause(first, AE.TOKEN_REFUSED)
        self.assertEqual((recorded['tokenRefused'], recorded['refusedFingerprint']), (True, NT.fingerprint(TOKEN)))
        _, before, reads = self.refused_dispatch('PRIOR_AUTH_TOKEN_NOT_REPLACED')
        self.assertNothingReserved(before)
        # the Owner enters the same token again: still refused
        same = self.enter(TOKEN)
        self.refused_dispatch('PRIOR_AUTH_TOKEN_NOT_REPLACED', provider=same)
        # a new token entered, but the entry the dispatcher reads still holds the refused one: nothing sent
        self.enter(NEW_TOKEN)
        stale = NS.ObservedProvider({NT.ENTRY: (NT.ENTRY_USER, TOKEN)})
        creates = len(self.server.creates)
        with self.assertRaises(di.DispatchRefused) as caught:
            self.dispatch_native(stale)
        self.assertEqual(caught.exception.code, 'NATIVE_TOKEN_NOT_REPLACED')
        self.assertEqual(len(self.server.creates), creates)
        failed = max(self.store.attempts(['failed']), key=lambda r: self.ordinal(r.operation_key))
        self.assertEqual(self.detail(failed.operation_key, 'failed')['code'], 'NATIVE_TOKEN_NOT_REPLACED')
        # the new token in the entry: admitted, and the create carries the new token, never the refused one
        fresh = NS.ObservedProvider({NT.ENTRY: (NT.ENTRY_USER, NEW_TOKEN)})
        second = self.dispatch_native(fresh)
        [(_, _, body)] = [c for c in self.server.creates if c[2]['conversation_id'] == second.conversation_id]
        self.assertEqual(body['secrets']['CLAUDE_CODE_OAUTH_TOKEN']['value'], NEW_TOKEN)
        self.assertEqual(second.native_token['tokenFingerprint'], NT.fingerprint(NEW_TOKEN))

    def test_an_entry_receipt_older_than_the_refused_dispatch_does_not_replace_it(self):
        self.enter(NEW_TOKEN)              # entered before the attempt; the entry then held the refused token
        first = self.ended_on_auth()
        self.cause(first, AE.TOKEN_REFUSED)
        self.refused_dispatch('PRIOR_AUTH_TOKEN_NOT_REPLACED',
                              provider=NS.ObservedProvider({NT.ENTRY: (NT.ENTRY_USER, NEW_TOKEN)}))
        fresh = self.enter(NEW_TOKEN)      # entered again after the refusal: a newer receipt of another token
        self.assertEqual(self.ordinal(self.dispatch_native(fresh).operation_key), 2)

    def test_the_cause_record_s_rules(self):
        first = self.interrupted(SURFACED['rate-limit'][0])
        self.end(first)
        for cause, code in (('token-refused', 'AUTH_CAUSE_NOT_APPLICABLE'), ('whatever', 'AUTH_CAUSE_INVALID')):
            with self.assertRaises(di.DispatchRefused) as caught:
                self.cause(first, cause)
            self.assertEqual(caught.exception.code, code)
        self.setUp()
        first = self.ended_on_auth()
        recorded = self.cause(first, AE.TOKEN_REFUSED)
        self.assertEqual(self.cause(first, AE.TOKEN_REFUSED), recorded)      # repeat-safe
        with self.assertRaises(di.DispatchRefused) as caught:
            self.cause(first, 'provider-fault')
        self.assertEqual(caught.exception.code, 'AUTH_CAUSE_CONFLICT')
        key = AE.CAUSE_KEY.format(attempt_id=first.attempt_id)
        self.assertEqual([e.to_state for e in self.store.events(key)], ['reserved', 'dispatched', 'confirmed'])

    def test_the_entry_receipt_constants_are_the_entry_command_s(self):
        E = _load('aieh_native_token_entry', REPO / 'integrations' / 'credentials' / 'native_token_entry.py')
        self.assertEqual(AE.ENTRY_RECEIPT_PREFIX, f'credential/{E.SERVICE}/')
        self.assertEqual(AE.ENTRY_RECEIPT_FORMAT, E.credentials.RECEIPT_FORMAT)


class CauseCommand(EndFixture):
    def run_command(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = AE.main(list(argv))
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def test_the_engineering_manager_s_command(self):
        first = self.ended_on_auth()
        db = str(self.case / 'integration.sqlite')
        args = ('record-auth-cause', '--store', db, '--operation-key', first.operation_key)
        code, out, err = self.run_command(*args, '--cause', 'token-refused')
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)['cause'], 'token-refused')
        self.assertEqual(json.loads(out)['recordedBy'], 'engineering-manager')
        self.assertEqual(self.run_command(*args, '--cause', 'token-refused')[0], 0)
        code, _, err = self.run_command(*args, '--cause', 'provider-fault')
        self.assertEqual(code, 1)
        self.assertIn('AUTH_CAUSE_CONFLICT', err)
        self.assertEqual(self.run_command(*args, '--cause', 'nonsense')[0], 2)
        self.assertEqual(self.run_command('record-auth-cause', '--store', str(self.case / 'none.sqlite'),
                                          '--operation-key', first.operation_key, '--cause', 'provider-fault')[0], 2)
        self.assertNotIn(TOKEN, out + err)


class UnclassifiedEndCause(EndFixture):
    """The engineering manager's classification of an unclassified end (``record-end-cause``): a separate receipt,
    the end record unchanged; interruption admits a new attempt, security-stop never does."""

    def unclassified(self):
        first = self.interrupted()
        self.assertEqual(self.end(first)['classification'], AE.UNCLASSIFIED)
        return first, AE.end_record(self.store, first.attempt_id)

    def classify_end(self, result, cause):
        return AE.record_end_cause(self.store, result.operation_key, cause=cause, actor='engineering-manager')

    def test_an_interruption_cause_admits_a_new_attempt_and_leaves_the_end_record_unchanged(self):
        first, ended = self.unclassified()
        end_key = AE.END_KEY.format(attempt_id=first.attempt_id)
        events = self.store.events(end_key)
        _, before, reads = self.refused_dispatch('PRIOR_END_UNCLASSIFIED')
        self.assertNothingReserved(before)
        self.assertEqual(self.provider.reads, reads)
        recorded = self.classify_end(first, AE.END_CAUSE_INTERRUPTION)
        self.assertEqual({k: recorded[k] for k in ('format', 'attemptId', 'cause', 'classification', 'endRecord',
                                                   'recordedBy')},
                         {'format': AE.END_CAUSE_FORMAT, 'attemptId': first.attempt_id, 'cause': 'interruption',
                          'classification': AE.INTERRUPTION, 'endRecord': end_key, 'recordedBy': 'engineering-manager'})
        self.assertEqual((AE.end_record(self.store, first.attempt_id), self.store.events(end_key)), (ended, events))
        second = self.dispatch_native()
        self.assertEqual(self.ordinal(second.operation_key), 2)
        self.assertNotEqual(second.conversation_id, first.conversation_id)

    def test_a_security_stop_cause_refuses_every_new_attempt(self):
        first, _ = self.unclassified()
        self.classify_end(first, AE.END_CAUSE_SECURITY_STOP)
        for _ in range(2):
            _, before, reads = self.refused_dispatch('PRIOR_END_SECURITY_STOP')
            self.assertNothingReserved(before)
            self.assertEqual(self.provider.reads, reads)

    def test_only_an_unclassified_end_is_classified(self):
        unended = self.dispatch_native()
        with self.assertRaises(di.DispatchRefused) as caught:
            self.classify_end(unended, AE.END_CAUSE_INTERRUPTION)
        self.assertEqual(caught.exception.code, 'END_CAUSE_NOT_APPLICABLE')
        for events in ((SURFACED['rate-limit'][0],), (SURFACED['oauth-expired'][0],)):
            with self.subTest(events[0]['code']):
                self.setUp()
                result = self.interrupted(*events)
                self.end(result)
                with self.assertRaises(di.DispatchRefused) as caught:
                    self.classify_end(result, AE.END_CAUSE_INTERRUPTION)
                self.assertEqual(caught.exception.code, 'END_CAUSE_NOT_APPLICABLE')
                self.assertIsNone(self.store.get(AE.END_CAUSE_KEY.format(attempt_id=result.attempt_id)))
        self.setUp()
        result = self.interrupted(SURFACED['rate-limit'][0])
        self.end(result, records=[record('egress-stop')])
        with self.assertRaises(di.DispatchRefused) as caught:
            self.classify_end(result, AE.END_CAUSE_INTERRUPTION)   # a security stop is never re-classified
        self.assertEqual(caught.exception.code, 'END_CAUSE_NOT_APPLICABLE')

    def test_repeat_safe_conflicting_and_invalid(self):
        first, _ = self.unclassified()
        with self.assertRaises(di.DispatchRefused) as caught:
            self.classify_end(first, 'retry')
        self.assertEqual(caught.exception.code, 'END_CAUSE_INVALID')
        recorded = self.classify_end(first, AE.END_CAUSE_INTERRUPTION)
        self.assertEqual(self.classify_end(first, AE.END_CAUSE_INTERRUPTION), recorded)
        key = AE.END_CAUSE_KEY.format(attempt_id=first.attempt_id)
        self.assertEqual([e.to_state for e in self.store.events(key)], ['reserved', 'dispatched', 'confirmed'])
        # a receipt holding another intent (written by hand) is a conflict, never overwritten
        self.setUp()
        other, _ = self.unclassified()
        self.store.reserve(AE.END_CAUSE_KEY.format(attempt_id=other.attempt_id), {'format': 'x'}, actor='hand')
        with self.assertRaises(di.DispatchRefused) as caught:
            self.classify_end(other, AE.END_CAUSE_INTERRUPTION)
        self.assertEqual(caught.exception.code, 'END_CAUSE_CONFLICT')

    def test_a_crash_before_the_record_is_resumed(self):
        first, _ = self.unclassified()
        key = AE.ESCALATION_KEY.format(attempt_id=first.attempt_id)
        real = di._mark

        def mark(integration_store, k, from_state, to_state, *args):
            if k == key and to_state == 'confirmed':
                raise Crash()
            real(integration_store, k, from_state, to_state, *args)
        with mock.patch.object(di, '_mark', mark), self.assertRaises(Crash):
            self.classify_end(first, AE.END_CAUSE_SECURITY_STOP)
        self.assertEqual(self.store.get(key).state, 'dispatched')
        self.refused_dispatch('PRIOR_END_UNCLASSIFIED')            # not classified until the record exists
        self.assertEqual(self.classify_end(first, AE.END_CAUSE_SECURITY_STOP)['cause'], 'security-stop')
        self.refused_dispatch('PRIOR_END_SECURITY_STOP')

    def test_the_command_and_its_task_target(self):
        first, _ = self.unclassified()
        args = ('record-end-cause', '--store', str(self.case / 'integration.sqlite'),
                '--operation-key', first.operation_key)
        code, out, err = CauseCommand.run_command(self, *args, '--cause', 'interruption')
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)['classification'], AE.INTERRUPTION)
        self.assertEqual(CauseCommand.run_command(self, *args, '--cause', 'interruption')[0], 0)
        code, out, err = CauseCommand.run_command(self, *args, '--cause', 'security-stop')   # an escalation
        self.assertEqual(code, 0, err)
        self.assertEqual((json.loads(out)['format'], json.loads(out)['supersedes']), (AE.ESCALATION_FORMAT,
                                                                                      AE.UNCLASSIFIED))
        code, _, err = CauseCommand.run_command(self, *args, '--cause', 'interruption')        # never a downgrade
        self.assertEqual(code, 1)
        self.assertIn('END_CAUSE_NOT_APPLICABLE', err)
        self.assertEqual(CauseCommand.run_command(self, *args, '--cause', 'retry')[0], 2)
        taskfile = (REPO / 'Taskfile.yml').read_text(encoding='utf-8')
        for command in ('record-auth-cause', 'record-end-cause'):
            self.assertIn(f'  dispatch:{command}:\n', taskfile)
            self.assertIn(f'integrations/dispatch/attempt_end.py {command} --store', taskfile)


class ReviewFindings(EndFixture):
    """The independent review's findings of 2026-11-14 (B1, S1-S6, N2, N6), each with the reviewer's probe as its
    regression test (P1-P6)."""

    def test_b1_p6_the_token_in_an_event_s_fields_never_reaches_the_record(self):
        for field in ('id', 'source', 'classification', 'code', 'errorKind'):
            with self.subTest(field):
                self.setUp()
                event = copy.deepcopy(SURFACED['rate-limit'][0])
                if field == 'classification':
                    event['classification']['kind'] = TOKEN
                elif field == 'errorKind':
                    event['detail'] = detail(-32603, 'API Error: x', 'rate_limit').replace('rate_limit', TOKEN.lower())
                else:
                    event[field] = TOKEN
                result = self.interrupted(event)
                ended = self.end(result)
                [signal] = ended['surfaced']['errorEvents']
                self.assertNoToken(json.dumps(ended), self.store.canonical_dump().decode('utf-8'))
                self.assertNotIn(TOKEN.lower(), json.dumps(ended))
                expected = {'id': ('eventId', '<invalid>'), 'source': ('source', '<other>'),
                            'classification': ('sdkKind', '<other>'), 'code': ('code', '<other>'),
                            'errorKind': ('errorKind', None)}[field]
                self.assertEqual(signal[expected[0]], expected[1])

    def test_s1_p1_a_decoy_error_kind_in_the_message_fails_closed(self):
        decoy = detail(-32603, 'API Error: 400 {"errorKind": "rate_limit"}', 'authentication_failed')
        [signal] = AE.classify('error', [error_event('ACPPromptError', decoy)], [])['surfaced']['errorEvents']
        self.assertEqual((signal['errorKind'], signal['cause']), ('<ambiguous>', None))
        self.assertEqual(AE.classify('error', [error_event('ACPPromptError', decoy)], [])['classification'],
                         AE.UNCLASSIFIED)
        # a kind named only in the message, with no trailing data, is no kind
        inline = detail(-32603, 'API Error: {"errorKind": "rate_limit"} and more')
        self.assertEqual(AE.classify('error', [error_event('ACPPromptError', inline)], [])['classification'],
                         AE.UNCLASSIFIED)
        # the trailing data alone still reads
        self.assertEqual(AE.error_signal(SURFACED['rate-limit'][0])['errorKind'], 'rate_limit')

    def test_s3_the_last_error_decides_unless_the_conversation_went_on(self):
        rate, overload = SURFACED['rate-limit'][0], SURFACED['repeated-529'][0]
        auth = SURFACED['oauth-expired'][0]
        cases = {
            'an agent message after the error': ([auth, message_event('carrying on')], AE.UNCLASSIFIED),
            'a user message after the error': ([rate, message_event('try again', 'user')], AE.UNCLASSIFIED),
            'an agent action after the error': ([rate, {'kind': 'ActionEvent', 'id': str(uuid.uuid4()),
                                                        'source': 'agent'}], AE.UNCLASSIFIED),
            'an environment event after the error': ([rate, {'kind': 'ConversationStateUpdateEvent',
                                                             'id': str(uuid.uuid4()), 'source': 'environment'}],
                                                     AE.INTERRUPTION),
            'an earlier auth refusal, then an overload last': ([auth, message_event('again', 'user'), overload],
                                                               AE.INTERRUPTION),
        }
        for name, (events, classification) in cases.items():
            with self.subTest(name):
                verdict = AE.classify('error', events, [])
                self.assertEqual(verdict['classification'], classification)
        verdict = AE.classify('error', [auth, message_event('again', 'user'), overload], [])
        self.assertEqual((verdict['causes'], verdict['surfaced']['classifiedFrom']), (['overload'], overload['id']))

    def test_s2_security_stop_escalates_an_interruption_or_an_authentication_refusal(self):
        for event in (SURFACED['rate-limit'][0], SURFACED['oauth-expired'][0]):
            with self.subTest(event['code']):
                self.setUp()
                result = self.interrupted(event)
                ended = self.end(result)
                with self.assertRaises(di.DispatchRefused) as caught:   # never a downgrade
                    AE.record_end_cause(self.store, result.operation_key, cause=AE.END_CAUSE_INTERRUPTION, actor='em')
                self.assertEqual(caught.exception.code, 'END_CAUSE_NOT_APPLICABLE')
                AE.record_end_cause(self.store, result.operation_key, cause=AE.END_CAUSE_SECURITY_STOP, actor='em')
                self.assertEqual(AE.end_record(self.store, result.attempt_id), ended)   # unchanged
                self.refused_dispatch('PRIOR_END_SECURITY_STOP')
        self.setUp()
        result = self.interrupted(SURFACED['rate-limit'][0])
        self.end(result, records=[record('containment-stop')])
        with self.assertRaises(di.DispatchRefused) as caught:
            AE.record_end_cause(self.store, result.operation_key, cause=AE.END_CAUSE_SECURITY_STOP, actor='em')
        self.assertEqual(caught.exception.code, 'END_CAUSE_NOT_APPLICABLE')

    def test_s5_p3_a_finished_earlier_attempt_refuses_with_its_own_code(self):
        first = self.dispatch_native()
        self.server.set(first.conversation_id, status='finished', runtime='missing')
        exc, before, _ = self.refused_dispatch('PRIOR_ATTEMPT_FINISHED')
        self.assertIn('result path', exc.detail)
        self.assertNothingReserved(before)
        self.server.set(first.conversation_id, status='running')
        self.refused_dispatch('PRIOR_ATTEMPT_NOT_ENDED')

    def test_s6_a_security_stop_refuses_every_stage_and_revision_of_the_work_item(self):
        review = self.resolve(self.d1_request(repository='other-app', stage='review', catalog_pin='reviewer-pin'),
                              self.manifest, self.d1_sources)

        def admit():
            return AE.admit_new_attempt(self.store, review, transport=self.server, read_artifact=self.read_artifact)
        self.assertEqual(admit().refused, ())          # positive control: no prior on the review triple
        first = self.interrupted(SURFACED['rate-limit'][0])
        self.end(first, records=[record('credential-stop')])
        with self.assertRaises(di.DispatchRefused) as caught:
            admit()
        self.assertEqual(caught.exception.code, 'PRIOR_END_SECURITY_STOP')
        self.assertEqual([r['workId'] for r in AE.work_item_ends(self.store, 'TASK-2')], ['TASK-2'])
        self.assertEqual(AE.work_item_ends(self.store, 'TASK-9'), [])

    def test_d1_q2_a_cut_detail_classifies_nothing(self):
        tail = ': {"errorKind": "rate_limit"}'
        prefix = '[-32603] API Error: 400 '
        pad = 'x' * (500 - len(prefix) - len(tail))
        cut = (prefix + pad + tail + ': {"errorKind": "authentication_failed"}')[:500]   # the reviewer's probe Q2
        self.assertEqual(len(cut), AE.DETAIL_CUT)
        [signal] = AE.classify('error', [error_event('ACPPromptError', cut)], [])['surfaced']['errorEvents']
        self.assertEqual((signal['errorKind'], signal['cause']), (None, None))
        self.assertEqual(AE.classify('error', [error_event('ACPPromptError', cut)], [])['classification'],
                         AE.UNCLASSIFIED)
        longer = detail(-32603, 'API Error: ' + 'y' * 600, 'rate_limit')
        self.assertEqual(AE.error_signal(error_event('ACPPromptError', longer))['errorKind'], None)
        short = detail(-32603, 'API Error: ' + 'y' * 400, 'rate_limit')    # under the cut: read
        self.assertLess(len(short), AE.DETAIL_CUT)
        self.assertEqual(AE.error_signal(error_event('ACPPromptError', short))['cause'], 'usage-limit')

    def test_d2_q3_an_escalation_supersedes_an_interruption_cause_and_is_never_downgraded(self):
        # an unclassified end the engineering manager classified as an interruption, then escalates
        first = self.interrupted()
        ended = self.end(first)
        AE.record_end_cause(self.store, first.operation_key, cause=AE.END_CAUSE_INTERRUPTION, actor='em')
        escalated = AE.record_end_cause(self.store, first.operation_key, cause=AE.END_CAUSE_SECURITY_STOP, actor='em')
        self.assertEqual((escalated['format'], escalated['classification'], escalated['supersedes']),
                         (AE.ESCALATION_FORMAT, AE.NON_RETRYABLE, AE.UNCLASSIFIED))
        self.assertEqual(AE.record_end_cause(self.store, first.operation_key, cause=AE.END_CAUSE_SECURITY_STOP,
                                             actor='em'), escalated)                  # repeat-safe
        self.assertEqual(AE.end_record(self.store, first.attempt_id), ended)          # unchanged
        self.assertEqual(AE.end_cause_record(self.store, first.attempt_id)['cause'], 'interruption')   # kept
        self.refused_dispatch('PRIOR_END_SECURITY_STOP')
        with self.assertRaises(di.DispatchRefused) as caught:                         # never a downgrade
            AE.record_end_cause(self.store, first.operation_key, cause=AE.END_CAUSE_INTERRUPTION, actor='em')
        self.assertEqual(caught.exception.code, 'END_CAUSE_NOT_APPLICABLE')
        # an unclassified end escalated first: an interruption cause is then refused
        self.setUp()
        second = self.interrupted()
        self.end(second)
        AE.record_end_cause(self.store, second.operation_key, cause=AE.END_CAUSE_SECURITY_STOP, actor='em')
        with self.assertRaises(di.DispatchRefused) as caught:
            AE.record_end_cause(self.store, second.operation_key, cause=AE.END_CAUSE_INTERRUPTION, actor='em')
        self.assertEqual(caught.exception.code, 'END_CAUSE_NOT_APPLICABLE')
        self.assertIsNone(AE.end_cause_record(self.store, second.attempt_id))
        self.refused_dispatch('PRIOR_END_SECURITY_STOP')

    def test_n_b_a_hook_message_after_the_error_is_not_the_conversation_going_on(self):
        verdict = AE.classify('error', [SURFACED['rate-limit'][0], message_event('x', 'hook')], [])
        self.assertEqual(verdict['classification'], AE.INTERRUPTION)

    def test_n2_p5_a_concurrent_second_end_returns_a_stable_code(self):
        result = self.interrupted(SURFACED['rate-limit'][0])
        key = AE.END_KEY.format(attempt_id=result.attempt_id)
        real, raced = di._mark, []

        def racing(integration_store, k, from_state, to_state, *args):
            if k == key and from_state == 'reserved' and not raced:
                raced.append(1)
                real(integration_store, k, from_state, to_state, *args)   # the other process moves it first
            real(integration_store, k, from_state, to_state, *args)
        with mock.patch.object(di, '_mark', racing):
            self.refused_end('ATTEMPT_END_CONFLICT', result)
        self.assertEqual(self.end(result)['classification'], AE.INTERRUPTION)
        self.assertEqual(self.end_keys(), [key])

    def test_n6_a_record_ref_never_holds_a_token_shape(self):
        for ref in (TOKEN, 'evidence:' + TOKEN, 'x/sk-ant-oat01-abcdefgh'):
            with self.subTest(ref=ref[:20]), self.assertRaises(di.DispatchRefused) as caught:
                AE.check_records([record('egress-stop', ref=ref)])
            self.assertEqual(caught.exception.code, 'DISPATCHER_RECORD_INVALID')
            self.assertNotIn(TOKEN, json.dumps(caught.exception.to_json(), default=str))


class TokenNeverAgain(EndFixture):
    def test_the_ended_attempt_is_never_dispatched_again(self):
        first = self.interrupted(SURFACED['rate-limit'][0])
        self.end(first)
        with self.assertRaises(di.DispatchRefused) as caught:
            di.reserved_inputs(self.store, first.operation_key)
        self.assertEqual(caught.exception.code, 'ATTEMPT_NOT_RESERVED')
        self.dispatch_native()
        creates = [c[2]['conversation_id'] for c in self.server.creates]
        self.assertEqual(len(creates), len(set(creates)), 'one create per conversation, never a second delivery')
        token_calls = [c for c in self.server.calls if c[2] is not None and TOKEN in json.dumps(c[2])]
        self.assertEqual([c[2]['conversation_id'] for c in token_calls], creates)

    def test_no_record_or_report_carries_the_token(self):
        first = self.interrupted(SURFACED['oauth-expired'][0])
        out, refusal = io.StringIO(), ''
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            ended = self.end(first)
            recorded = AE.record_auth_cause(self.store, first.operation_key, cause=AE.TOKEN_REFUSED, actor='em')
            try:
                self.dispatch_native()
            except di.DispatchRefused as exc:
                refusal = json.dumps(exc.to_json(), default=str)
        dump = self.store.canonical_dump().decode('utf-8')
        self.assertIn(NT.fingerprint(TOKEN), dump)
        self.assertNoToken(dump, json.dumps(ended), json.dumps(recorded), refusal, out.getvalue())


class ClientQuery(unittest.TestCase):
    def test_only_the_event_search_takes_its_page_id(self):
        calls = []
        client = cc.client(lambda m, p, b: calls.append((m, p)) or {'status': 200, 'body': {}})
        cid = str(uuid.uuid4())
        client.call('GET', AE.EVENTS_ROUTE, params={'conversation_id': cid}, query={'page_id': 'abc-1'})
        self.assertEqual(calls, [('GET', f'/api/conversations/{cid}/events/search?page_id=abc-1')])
        for route, query in ((AE.EVENTS_ROUTE, {'limit': '5'}), (AE.EVENTS_ROUTE, {'page_id': 'a&b=c'}),
                             (AE.EVENTS_ROUTE, {}), (AE.CONVERSATION_ROUTE, {'page_id': 'x'}),
                             (AE.EVENTS_ROUTE, {'page_id': 'x', 'kind': 'y'})):
            with self.subTest(route=route, query=query), self.assertRaises(di.DispatchRefused) as caught:
                client.call('GET', route, params={'conversation_id': cid}, query=query)
            self.assertEqual(caught.exception.code, 'ROUTE_PARAMETER_INVALID')
        self.assertEqual(len(calls), 1)

    def test_the_routes_the_end_uses_are_dispatcher_allowed(self):
        client = cc.client(lambda m, p, b: None)
        for method, route in (('GET', AE.CONVERSATION_ROUTE), ('GET', AE.EVENTS_ROUTE), ('GET', AE.RUNTIME_ROUTE),
                              ('DELETE', AE.RUNTIME_ROUTE)):
            self.assertTrue(client.allows(method, route), (method, route))


if __name__ == '__main__':
    unittest.main()
