"""Tests for the native conversation create (plan leaf E-01.3.1).

Run from the repository root:

    python -I -B -m unittest discover -s integrations/dispatch/tests -v

The proof, rule by rule, with an injected transport (a fake Agent Server that replays the pinned
1.60.1 server's recorded answers, ``fixtures/agent-server-1.60.1-exchange.json``):

* the request carries the reserved conversation id and ``conversation_runtime`` docker, and the
  answer's identifiers are captured (``create_receipt``) without storing anything else of it;
* every dispatcher call, not only the create, is checked against the profile's route allowlist
  (``routes.json``, ``dispatcher`` ``allowed``): a call that is not listed is refused before it is
  sent, so the transport is never called;
* before a create, ``GET /server_info`` must show decision 0001's preconditions P1 to P5, and a
  failed precondition refuses the create;
* the order is resolve, reserve, admit, send_create; send_create receives the reserved record
  re-read from the store; a refused attempt is marked failed;
* the host workspace is created only after admission, and never through a link or junction;
* every reservation carries workRef and outcomeRef.

Every refusal asserts that the create was never sent (and, where nothing may be called, that the
transport was called zero times); every positive control that it was sent exactly once with the
exact body. Everything lives in throwaway directories under the default TEMP and an
AIEH_DATA_ROOT inside them. No guest, Agent Server, network or LLM is used.
"""
from pathlib import Path
import copy
import dataclasses
import hashlib
import importlib.util
import json
import os
import sys
import unittest
from unittest import mock

CATEGORY = 'integration'

HERE = Path(__file__).resolve().parent


def _load(name, path):
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


adm = _load('test_dispatch_admission', HERE / 'test_dispatch_admission.py')
base = adm.base
di = base.di
store_mod = base.store_mod
EXCHANGE = adm.EXCHANGE
SERVER_INFO = EXCHANGE['server_info']['response']
CREATE_ANSWER = EXCHANGE['create']['response']
ROUTES_BYTES = base.ROUTES_BYTES
ROUTES_SHA = hashlib.sha256(ROUTES_BYTES).hexdigest()
ROUTES = json.loads(ROUTES_BYTES)
CONVERSATION = '929f0d8a-f3d8-4da3-8ac3-9d0017709d71'
CREATE = ('POST', '/api/conversations')
INFO = ('GET', '/server_info')


class Recorder:
    """A transport that records every call and answers ``answer``."""

    def __init__(self, answer=None):
        self.calls, self.answer = [], answer

    def __call__(self, method, path, body):
        self.calls.append((method, path, copy.deepcopy(body)))
        return self.answer


def client(transport, routes=ROUTES_BYTES):
    return di.AgentServerClient(routes, transport, routes_sha256=hashlib.sha256(routes).hexdigest())


def routes_variant(change):
    data = json.loads(ROUTES_BYTES)
    change(data)
    return json.dumps(data, indent=1).encode('utf-8')


def entry(data, method, path):
    return next(r for r in data['routes'] if (r['method'], r['path']) == (method, path))


VALID_PARAMETER = {'conversation_id': CONVERSATION, 'event_id': 'event-1'}


class RouteAllowlistTests(unittest.TestCase):
    """Every dispatcher call is checked against the pinned allowlist before the transport."""
    category = 'unit'

    def refused(self, code, transport, method, route, **kwargs):
        with self.assertRaises(di.DispatchRefused) as caught:
            client(transport).call(method, route, **kwargs)
        self.assertEqual(caught.exception.code, code, caught.exception.detail)
        self.assertEqual(transport.calls, [], 'a refused call must never reach the transport')
        return caught.exception

    def test_each_listed_route_is_sent_only_when_the_dispatcher_is_allowed(self):
        """Over the whole pinned allowlist: allowed routes reach the transport once with the
        rendered path; validation and not-used routes are refused with zero calls."""
        seen = {'allowed': 0, 'validation': 0, 'not-used': 0}
        for route in ROUTES['routes']:
            names = di.PLACEHOLDER_RE.findall(route['path'])
            params = {name: VALID_PARAMETER.get(name, 'x') for name in names}
            body = None if route['method'] in di.BODYLESS_METHODS else {}
            transport = Recorder({'status': 200, 'body': {}})
            seen[route['dispatcher']] += 1
            with self.subTest(method=route['method'], path=route['path'], dispatcher=route['dispatcher']):
                if route['dispatcher'] == 'allowed':
                    client(transport).call(route['method'], route['path'], params=params, body=body)
                    path = route['path']
                    for name, value in params.items():
                        path = path.replace('{' + name + '}', value)
                    self.assertEqual(transport.calls, [(route['method'], path, body)])
                else:
                    self.refused('ROUTE_NOT_ALLOWLISTED', transport, route['method'], route['path'],
                                 params=params, body=body)
        self.assertTrue(all(seen.values()), seen)
        allowed = client(Recorder())
        self.assertTrue(allowed.allows(*INFO) and allowed.allows(*CREATE))
        self.assertEqual(allowed.version, '1.60.1')

    def test_unlisted_calls_are_refused_before_the_transport(self):
        cases = {
            'unknown path': ('GET', '/api/conversations/everything'),
            'another method on an allowed path': ('PUT', '/api/conversations'),
            'a concrete path instead of the template': ('GET', f'/api/conversations/{CONVERSATION}'),
            'a query string': ('GET', '/server_info?x=1'),
            'a trailing slash': ('GET', '/server_info/'),
            'a case variant': ('GET', '/Server_Info'),
            'a lower-case method': ('get', '/server_info'),
            'a validation route': ('GET', '/api/conversations/{conversation_id}/bash/bash_events/{tail}'),
            'a not-used route': ('POST', '/api/conversations/{conversation_id}/pause'),
            'not text': (None, '/server_info'),
            'a WebSocket': ('WEBSOCKET', '/sockets/events/{conversation_id}'),
        }
        for name, (method, route) in cases.items():
            with self.subTest(name):
                self.refused('ROUTE_NOT_ALLOWLISTED', Recorder(), method, route)

    def test_an_allowed_route_listed_twice_or_marked_otherwise_is_refused(self):
        def twice(data):
            data['routes'].append(dict(entry(data, *INFO)))

        def validation(data):
            entry(data, *INFO)['dispatcher'] = 'validation'

        for name, change in (('listed twice', twice), ('validation', validation)):
            with self.subTest(name):
                transport = Recorder()
                with self.assertRaises(di.DispatchRefused) as caught:
                    client(transport, routes_variant(change)).call(*INFO)
                self.assertEqual(caught.exception.code, 'ROUTE_NOT_ALLOWLISTED')
                self.assertEqual(transport.calls, [])

    def test_path_parameters_must_be_exactly_the_placeholders_in_grammar(self):
        route = '/api/conversations/{conversation_id}'
        cases = {
            'missing': {},
            'extra': {'conversation_id': CONVERSATION, 'event_id': 'event-1'},
            'traversal': {'conversation_id': '../server_info'},
            'a slash': {'conversation_id': CONVERSATION + '/runtime'},
            'upper case': {'conversation_id': CONVERSATION.upper()},
            'no hyphens': {'conversation_id': CONVERSATION.replace('-', '')},
            'empty': {'conversation_id': ''},
            'not text': {'conversation_id': 5},
            'a query': {'conversation_id': CONVERSATION + '?x=1'},
        }
        for name, params in cases.items():
            with self.subTest(name):
                self.refused('ROUTE_PARAMETER_INVALID', Recorder(), 'GET', route, params=params)
        transport = Recorder()
        client(transport).call('GET', route, params={'conversation_id': CONVERSATION})
        self.assertEqual(transport.calls, [('GET', f'/api/conversations/{CONVERSATION}', None)])
        # An event id stays one segment; a placeholder outside the known grammars is refused.
        self.refused('ROUTE_PARAMETER_INVALID', Recorder(), 'GET', '/api/conversations/{conversation_id}/events/{event_id}',
                     params={'conversation_id': CONVERSATION, 'event_id': '../../x'})

        def unknown_placeholder(data):
            data['routes'].append({**entry(data, 'GET', route), 'path': '/api/conversations/{other}'})
        transport = Recorder()
        with self.assertRaises(di.DispatchRefused) as caught:
            client(transport, routes_variant(unknown_placeholder)).call(
                'GET', '/api/conversations/{other}', params={'other': CONVERSATION})
        self.assertEqual(caught.exception.code, 'ROUTE_PARAMETER_INVALID')
        self.assertEqual(transport.calls, [])

    def test_a_bodyless_method_takes_no_body(self):
        self.refused('BODY_MALFORMED', Recorder(), 'GET', '/server_info', body={})

    def test_the_allowlist_itself_is_pinned(self):
        with self.assertRaises(di.DispatchRefused) as caught:
            di.AgentServerClient(ROUTES_BYTES + b' ', Recorder(), routes_sha256=ROUTES_SHA)
        self.assertEqual(caught.exception.code, 'PROFILE_ARTIFACT_DRIFTED')
        for name, change in (('no version', lambda d: d.pop('version')), ('empty version', lambda d: d.update(version='')),
                             ('other schema', lambda d: d.update(schema='x')),
                             ('routes not a list', lambda d: d.update(routes={}))):
            with self.subTest(name), self.assertRaises(di.DispatchRefused) as caught:
                client(Recorder(), routes_variant(change))
            self.assertEqual(caught.exception.code, 'PROFILE_ARTIFACT_INVALID')
        with self.assertRaises(TypeError):
            di.AgentServerClient(ROUTES_BYTES, None, routes_sha256=ROUTES_SHA)


def info_with(**changes):
    answer = copy.deepcopy(SERVER_INFO)
    for key, value in changes.items():
        if value is KeyError:
            answer['body'].pop(key)
        else:
            answer['body'][key] = value
    return answer


def capabilities_without(name):
    return [c for c in SERVER_INFO['body']['capabilities'] if c != name]


# Each case breaks exactly the named precondition (decision 0001; F-04.1c's recorded answer otherwise).
PRECONDITION_CASES = {
    'P1': {
        '500': {**copy.deepcopy(SERVER_INFO), 'status': 500},
        '404': {**copy.deepcopy(SERVER_INFO), 'status': 404},
        'status as text': {**copy.deepcopy(SERVER_INFO), 'status': '200'},
        'another version': info_with(version='1.60.0'),
        'the 1.58.2 line': info_with(version='1.58.2'),
        'no version': info_with(version=KeyError),
        'version as a number': info_with(version=1.601),
    },
    'P2': {'no conversation_runtime_routes_v1': info_with(
        capabilities=capabilities_without('conversation_runtime_routes_v1'))},
    'P3': {'no idempotent_conversation_create_v1': info_with(
        capabilities=capabilities_without('idempotent_conversation_create_v1'))},
    'P4': {'local': info_with(conversation_runtime='local'), 'case variant': info_with(conversation_runtime='Docker'),
           'absent': info_with(conversation_runtime=KeyError), 'process': info_with(conversation_runtime='process')},
    'P5': {'selectable (hybrid)': info_with(available_conversation_runtimes=['local', 'docker']),
           'docker only listed': info_with(available_conversation_runtimes=['docker']),
           'absent': info_with(available_conversation_runtimes=KeyError),
           'null': info_with(available_conversation_runtimes=None)},
}


class ServerPreconditionTests(unittest.TestCase):
    """Decision 0001's /server_info preconditions, P1 to P5, on the recorded answer and variants."""
    category = 'unit'

    def failed(self, answer):
        with self.assertRaises(di.DispatchRefused) as caught:
            di.server_preconditions(answer, '1.60.1')
        self.assertEqual(caught.exception.code, 'SERVER_PRECONDITION_FAILED')
        json.dumps(caught.exception.to_json())  # plain JSON: it is stored with the failed attempt
        return caught.exception.context['failed']

    def test_the_pinned_server_meets_every_precondition(self):
        observed = di.server_preconditions(copy.deepcopy(SERVER_INFO), '1.60.1')
        self.assertEqual((observed['version'], observed['conversation_runtime'],
                          observed['available_conversation_runtimes']), ('1.60.1', 'docker', []))
        self.assertEqual(sorted(di.PRECONDITIONS), ['P1', 'P2', 'P3', 'P4', 'P5'])

    def test_each_precondition_alone_refuses(self):
        for precondition, cases in PRECONDITION_CASES.items():
            for name, answer in cases.items():
                with self.subTest(precondition=precondition, case=name):
                    failed = self.failed(answer)
                    if answer.get('status') == 200:
                        self.assertEqual(failed, [precondition])
                    else:  # no answer object: nothing is established
                        self.assertEqual(failed, list(di.PRECONDITIONS))

    def test_several_failures_are_all_named(self):
        answer = info_with(conversation_runtime='local', available_conversation_runtimes=['local', 'docker'],
                           capabilities=[])
        self.assertEqual(self.failed(answer), ['P2', 'P3', 'P4', 'P5'])
        for answer in (None, [], {'status': 200}, {'status': 200, 'body': []}, {'status': 200, 'body': 'x'}):
            with self.subTest(answer=answer):
                self.assertEqual(self.failed(answer), list(di.PRECONDITIONS))
        self.assertEqual(self.failed(info_with(capabilities='conversation_runtime_routes_v1 '
                                                            'idempotent_conversation_create_v1')), ['P2', 'P3'])

    def test_the_pinned_version_is_the_allowlist_s(self):
        with self.assertRaises(di.DispatchRefused):
            di.server_preconditions(copy.deepcopy(SERVER_INFO), '1.60.2')


class CreateReceiptTests(unittest.TestCase):
    """The answer's identifiers, typed; nothing else of it is kept."""
    category = 'unit'

    def test_created_and_existing(self):
        receipt = di.create_receipt(copy.deepcopy(CREATE_ANSWER), CONVERSATION)
        self.assertEqual(receipt, {'format': di.RECEIPT_FORMAT, 'executionRef': f'openhands:conversation/{CONVERSATION}',
                                   'conversationId': CONVERSATION, 'httpStatus': 201, 'created': True})
        existing = di.create_receipt({**copy.deepcopy(CREATE_ANSWER), 'status': 200}, CONVERSATION)
        self.assertEqual((existing['httpStatus'], existing['created']), (200, False))
        # The execution reference is the lineage reader's attempt reference.
        self.assertIsInstance(di.lineage.parse(receipt['executionRef']), di.lineage.AttemptRef)

    def test_anything_else_is_no_receipt(self):
        other = '00000000-0000-4000-8000-000000000000'
        cases = {
            'another id': {'status': 201, 'body': {**CREATE_ANSWER['body'], 'id': other}},
            'no id': {'status': 201, 'body': {k: v for k, v in CREATE_ANSWER['body'].items() if k != 'id'}},
            'hex id': {'status': 201, 'body': {**CREATE_ANSWER['body'], 'id': CONVERSATION.replace('-', '')}},
            '202': {**CREATE_ANSWER, 'status': 202}, '204': {'status': 204, 'body': None},
            '422': {'status': 422, 'body': {'detail': 'x'}}, '500': {'status': 500, 'body': None},
            'status as text': {**CREATE_ANSWER, 'status': '201'}, 'body a list': {'status': 201, 'body': []},
            'not a mapping': None,
        }
        for name, answer in cases.items():
            with self.subTest(name):
                self.assertIsNone(di.create_receipt(copy.deepcopy(answer), CONVERSATION))


class FakeAgentServer:
    """The pinned server, faked: GET /server_info and POST /api/conversations answer as recorded
    (the create's answer carries the request's conversation id); every call is recorded."""

    def __init__(self, info=None, info_error=None, create=None, create_error=None):
        self.calls = []
        self.info = copy.deepcopy(SERVER_INFO) if info is None else info
        self.info_error, self.create, self.create_error = info_error, create, create_error

    def __call__(self, method, path, body):
        self.calls.append((method, path, copy.deepcopy(body)))
        if (method, path) == INFO:
            if self.info_error is not None:
                raise self.info_error
            return copy.deepcopy(self.info)
        if (method, path) == CREATE:
            if self.create_error is not None:
                raise self.create_error
            if self.create is not None:
                return copy.deepcopy(self.create)
            answer = copy.deepcopy(CREATE_ANSWER)
            answer['body']['id'] = body['conversation_id']
            answer['body']['persistence_dir'] = '/var/openhands/conversations/' + body['conversation_id'].replace('-', '')
            return answer
        raise AssertionError(f'unexpected call {method} {path}')

    @property
    def creates(self):
        return [call for call in self.calls if call[:2] == CREATE]


class DispatchTests(adm.AdmissionFixture):
    """``dispatch``: the order, the store, the workspace and the answer, on the E-01.2.1 fixture."""

    def run_dispatch(self, transport, manifest=None, request=None, sources=None):
        manifest = manifest or self.write_manifest(self.manifest_data(), self.fresh('manifest'))
        return di.dispatch(self.request() if request is None else request, manifest=manifest,
                           work_sources=(self.sources if sources is None else sources).get,
                           integration_store=self.store, workspaces=self.workspaces, transport=transport,
                           actor='dispatch-test', read_profile=self.read_profile, read_artifact=self.read_artifact)

    def only(self, states=None):
        attempts = self.store.attempts(states)
        self.assertEqual(len(attempts), 1, attempts)
        return attempts[0]

    def latest(self, states=None):
        """The attempt with the highest ordinal (several attempts in one test, each terminal)."""
        return max(self.store.attempts(states),
                   key=lambda r: self.store.attempt_identity(r.operation_key).identity.ordinal)

    def last_event(self, key):
        return self.store.events(key)[-1]

    def refused_dispatch(self, code, transport, **kwargs):
        with self.assertRaises(di.DispatchRefused) as caught:
            self.run_dispatch(transport, **kwargs)
        self.assertEqual(caught.exception.code, code, caught.exception.detail)
        return caught.exception

    def assertFailedWith(self, key, code):
        """The attempt is failed, by the refusal's code, with the refusal as the transition's detail."""
        event = self.last_event(key)
        self.assertEqual((self.store.get(key).state, event.to_state, event.reason), ('failed', 'failed', code))
        self.assertEqual(json.loads(event.detail_json)['code'], code)

    # -- the positive control ------------------------------------------------

    def test_dispatch_sends_the_reserved_create_and_records_the_returned_ids(self):
        server = FakeAgentServer()
        result = self.run_dispatch(server)
        attempt = self.only()
        key = attempt.operation_key
        conversation = attempt.conversation_id
        self.assertEqual(conversation, store_mod.conversation_id_for(key))
        # Exactly two calls: the preconditions, then one create with the reserved id and docker.
        body = copy.deepcopy(adm.TEMPLATE)
        body['conversation_id'] = conversation
        self.assertEqual(server.calls, [('GET', '/server_info', None), ('POST', '/api/conversations', body)])
        self.assertEqual((body['conversation_runtime'], body['workspace']['working_dir']), ('docker', '/workspace'))
        # The returned identifiers, typed, and the store's record of them.
        self.assertEqual(result.to_json(), {
            'format': di.RESULT_FORMAT, 'operation_key': key, 'attempt_id': store_mod.attempt_id_for(key),
            'conversation_id': conversation, 'execution_ref': f'openhands:conversation/{conversation}',
            'http_status': 201, 'created': True, 'host_workspace': result.host_workspace})
        self.assertEqual(attempt.state, 'confirmed')
        events = self.store.events(key)
        self.assertEqual([(e.from_state, e.to_state, e.reason) for e in events],
                         [(None, 'reserved', 'reserved'), ('reserved', 'dispatched', 'create'),
                          ('dispatched', 'confirmed', 'created')])
        self.assertEqual(json.loads(events[1].detail_json), {
            'format': di.DISPATCHED_FORMAT, 'conversationId': conversation,
            'route': {'method': 'POST', 'path': '/api/conversations'}})
        self.assertEqual(json.loads(events[2].detail_json), {
            'format': di.RECEIPT_FORMAT, 'executionRef': f'openhands:conversation/{conversation}',
            'conversationId': conversation, 'httpStatus': 201, 'created': True})
        # Every reservation carries workRef and outcomeRef, the keys integrations/lineage reads.
        intent = json.loads(attempt.intent_json)
        self.assertEqual((intent['workRef'], intent['outcomeRef']), ('backlog:TASK-2', base.OUTCOME_REF))
        self.assertEqual(intent[di.INTENT_KEY]['outcome_ref'], base.OUTCOME_REF)
        self.assertIsInstance(di.lineage.parse(intent['outcomeRef']), di.lineage.ObjectiveRef)
        # No duplicate event history: nothing of the answer but its id reaches the store.
        dump = self.store.canonical_dump().decode('utf-8')
        for value in ('execution_status', 'persistence_dir', conversation.replace('-', ''), 'NeverConfirm',
                      'gpt-5.6', 'FinishTool', 'secret_registry', 'usage_to_metrics', '2026-11-07T07:25:46'):
            self.assertNotIn(value, dump)
        self.assertFalse(any('/events' in path for _, path, _ in server.calls))
        # The host workspace exists, as plain directories, after the create.
        workspace = Path(result.host_workspace)
        self.assertEqual(workspace, self.category.joinpath(*json.loads(attempt.intent_json)[di.INTENT_KEY]
                                                           ['planned_workspace'].split('/')))
        for step in (self.category, *[p for p in workspace.parents if p.is_relative_to(self.category)], workspace):
            di._real_directory(step)

    def test_every_call_goes_through_the_route_checked_client(self):
        """The transport is only ever called by AgentServerClient.call: both calls of a dispatch,
        the preconditions and the create, are checked against the pinned allowlist."""
        checked, real_call = [], di.AgentServerClient.call

        def spy(client_self, method, route, **kwargs):
            checked.append((method, route))
            return real_call(client_self, method, route, **kwargs)
        server = FakeAgentServer()
        with mock.patch.object(di.AgentServerClient, 'call', spy):
            self.run_dispatch(server)
        self.assertEqual(checked, [INFO, CREATE])
        self.assertEqual([call[:2] for call in server.calls], checked)

    def test_an_existing_conversation_is_confirmed_as_existing(self):
        """The pinned server answers 200 for a conversation that already has the id (F-04.2 s4.5)."""
        server = FakeAgentServer()

        def existing(method, path, body):
            result = server(method, path, body)
            if (method, path) == CREATE:
                result['status'] = 200
            return result
        result = self.run_dispatch(existing)
        self.assertEqual((result.http_status, result.created), (200, False))
        key = self.only(['confirmed']).operation_key
        self.assertEqual(self.last_event(key).reason, 'existing')
        self.assertIs(json.loads(self.last_event(key).detail_json)['created'], False)
        self.assertEqual(len(server.creates), 1)

    # -- the order and the re-read record ------------------------------------

    def test_the_order_is_resolve_reserve_admit_send_create_on_the_re_read_record(self):
        order, seen = [], {}
        real = {name: getattr(di, name) for name in ('resolve', 'reserved_inputs', 'admit', 'create_workspace',
                                                     'send_create')}
        reserve = self.store.reserve_attempt

        def spy(name):
            def wrapper(*args, **kwargs):
                order.append(name)
                if name == 'admit':
                    seen['admit'] = (args[0], [a.state for a in self.store.attempts()],
                                     os.path.lexists(self.category))
                if name == 'send_create':
                    seen['send'] = (kwargs['resolved'], [a.state for a in self.store.attempts()],
                                    os.path.isdir(args[0].host_workspace))
                result = real[name](*args, **kwargs)
                seen.setdefault(name + ' result', result)
                return result
            return wrapper

        def reserving(*args, **kwargs):
            order.append('reserve_attempt')
            return reserve(*args, **kwargs)

        with mock.patch.multiple(di, **{name: spy(name) for name in real}), \
                mock.patch.object(self.store, 'reserve_attempt', reserving):
            self.run_dispatch(FakeAgentServer())
        self.assertEqual(order, ['resolve', 'reserve_attempt', 'reserved_inputs', 'admit', 'create_workspace',
                                 'send_create'])
        resolved, reread = seen['resolve result'], seen['reserved_inputs result']
        # admit and send_create get the record re-read from the store, not the resolution's object.
        self.assertIs(seen['admit'][0], reread)
        self.assertIs(seen['send'][0], reread)
        self.assertIsNot(reread, resolved)
        self.assertEqual(reread, resolved)
        # Admission ran on a reserved attempt with no workspace category; the send on a dispatched
        # attempt whose workspace exists.
        self.assertEqual(seen['admit'][1:], (['reserved'], False))
        self.assertEqual(seen['send'][1:], (['dispatched'], True))

    def test_the_re_read_record_is_checked_against_the_store(self):
        """A stored intent that is not exactly the dispatch record of its typed identity is refused,
        and the attempt marked failed; the transport is never called."""
        key_box = {}
        real_get = self.store.get

        def tampering(change):
            def get(key):
                reservation = real_get(key)
                if reservation is None or reservation.state != 'reserved':
                    return reservation
                key_box['key'] = key
                intent = json.loads(reservation.intent_json)
                change(intent)
                text = store_mod.canonical_intent(intent)
                return store_mod.Reservation(**{**reservation.__dict__, 'intent_json': text,
                                                'intent_digest': hashlib.sha256(text.encode()).hexdigest()})
            return get

        cases = {
            'another outcome': lambda i: i.update(outcomeRef='outcome:00000000-0000-4000-8000-000000000000'),
            'no outcomeRef': lambda i: i.pop('outcomeRef'),
            'another work': lambda i: i.update(workRef='backlog:TASK-1'),
            'the record\'s outcome': lambda i: i[di.INTENT_KEY].update(outcome_ref='outcome:00000000-0000-4000-8000-'
                                                                                   '000000000000'),
            'another policy digest': lambda i: i[di.INTENT_KEY].update(policy_digest='0' * 64),
            'another record format': lambda i: i[di.INTENT_KEY].update(format=di.RESOLVED_FORMAT[:-1] + '1'),
            'an extra key': lambda i: i.update(extra=1),
            # A consistent forgery of the record and its identity: only the typed row tells.
            'record and identity forged together': lambda i: (
                i[di.INTENT_KEY].update(policy_digest='0' * 64),
                i[store_mod.IDENTITY_INTENT_KEY].update(policy_digest='0' * 64)),
        }
        for name, change in cases.items():
            with self.subTest(name):
                server = FakeAgentServer()
                with mock.patch.object(self.store, 'get', tampering(change)):
                    self.refused_dispatch('RESERVATION_INVALID', server)
                self.assertEqual(server.calls, [])
                self.assertFailedWith(key_box['key'], 'RESERVATION_INVALID')

    def test_reserved_inputs_refuses_what_is_not_a_reserved_dispatch_attempt(self):
        with self.assertRaises(di.DispatchRefused) as caught:
            di.reserved_inputs(self.store, 'attempt/v1/TASK-2/none/implement/1')
        self.assertEqual(caught.exception.code, 'RESERVATION_INVALID')
        self.store.reserve('legacy-key', {'workRef': 'backlog:TASK-2'}, actor='dispatch-test')
        with self.assertRaises(di.DispatchRefused) as caught:
            di.reserved_inputs(self.store, 'legacy-key')
        self.assertEqual(caught.exception.code, 'RESERVATION_INVALID')
        resolved = self.resolve()
        key = resolved.attempt_identity().operation_key
        self.store.reserve_attempt(resolved.attempt_identity(), resolved.intent(), actor='dispatch-test')
        self.assertEqual(di.reserved_inputs(self.store, key), resolved)
        self.store.transition(key, 'failed', actor='dispatch-test', reason='test')
        with self.assertRaises(di.DispatchRefused) as caught:
            di.reserved_inputs(self.store, key)
        self.assertEqual(caught.exception.code, 'ATTEMPT_NOT_RESERVED')

    # -- refusals: the attempt is failed, the create never sent --------------

    def test_a_resolution_refusal_reserves_nothing_and_calls_nothing(self):
        server = FakeAgentServer()
        self.refused_dispatch('REPOSITORY_NOT_APPROVED', server, request=self.request(repository='unknown-app'))
        self.assertEqual((server.calls, self.store.attempts()), ([], []))

    def test_an_admission_refusal_is_marked_failed_and_creates_no_workspace(self):
        manifest = self.approve_variant()
        routes = self.profiles / 'strong-test-profile' / 'agent-server' / 'routes.json'
        routes.write_bytes(routes.read_bytes() + b'\n')
        server = FakeAgentServer()
        self.refused_dispatch('PROFILE_ARTIFACT_DRIFTED', server, manifest=manifest)
        self.assertEqual(server.calls, [])
        self.assertFailedWith(self.only().operation_key, 'PROFILE_ARTIFACT_DRIFTED')
        self.assertFalse(os.path.lexists(self.category), 'admission refused: no workspace is created')

    def test_the_workspace_is_never_created_through_a_link_planted_after_admission(self):
        if sys.platform != 'win32':
            self.skipTest('junctions are a Windows reparse point')
        import _winapi
        real_admit = di.admit
        for name in ('category', 'repository', 'work'):
            with self.subTest(name):
                target, planted = self.case / f'elsewhere-{name}', []

                def planting(*args, **kwargs):
                    admitted = real_admit(*args, **kwargs)
                    parts = Path(admitted.host_workspace).relative_to(self.category).parts
                    link = {'category': self.category, 'repository': self.category / parts[0],
                            'work': self.category.joinpath(*parts[:2])}[name]
                    target.mkdir()
                    link.parent.mkdir(parents=True, exist_ok=True)
                    _winapi.CreateJunction(str(target), str(link))
                    planted.append(link)
                    return admitted
                server = FakeAgentServer()
                try:
                    with mock.patch.object(di, 'admit', planting):
                        self.refused_dispatch('WORKSPACE_PATH_UNSAFE', server)
                finally:
                    for link in planted:
                        os.rmdir(link)
                self.assertEqual(server.calls, [])
                self.assertEqual(self.store.attempts(['reserved', 'dispatched', 'unknown', 'confirmed']), [])
                self.assertFailedWith(self.latest().operation_key, 'WORKSPACE_PATH_UNSAFE')
                self.assertEqual(os.listdir(target), [], 'nothing was created through the junction')

    def test_a_link_that_wins_the_race_to_a_directory_is_refused(self):
        """A junction planted after the initial walk, exactly when a directory is created (the
        category by aieh_paths.ensure, a part by mkdir), is caught where it appears: nothing is
        created through it, and the create is never sent."""
        if sys.platform != 'win32':
            self.skipTest('junctions are a Windows reparse point')
        import _winapi
        real_mkdir, real_ensure = os.mkdir, di.paths.ensure
        for name in ('category', 'repository', 'work'):
            with self.subTest(name):
                target, planted = self.case / f'race-{name}', []
                if name != 'category':
                    self.category.mkdir(parents=True, exist_ok=True)

                def plant(link):
                    target.mkdir()
                    _winapi.CreateJunction(str(target), str(link))
                    planted.append(link)

                def ensure(category, res=None, *parts):
                    path = Path(str(res.paths[category]))
                    path.parent.mkdir(parents=True, exist_ok=True)
                    plant(path)
                    return path

                def mkdir(path, *args, **kwargs):
                    parts = Path(path).relative_to(self.category).parts if Path(path).is_relative_to(
                        self.category) else ()
                    if len(parts) == {'repository': 1, 'work': 2}.get(name):
                        plant(Path(path))
                    return real_mkdir(path, *args, **kwargs)
                server = FakeAgentServer()
                patches = [mock.patch.object(di.paths, 'ensure', ensure)] if name == 'category' else \
                    [mock.patch.object(di.os, 'mkdir', mkdir)]
                try:
                    with patches[0]:
                        self.refused_dispatch('WORKSPACE_PATH_UNSAFE', server)
                finally:
                    for link in planted:
                        os.rmdir(link)
                self.assertEqual(len(planted), 1)
                self.assertEqual(server.calls, [])
                self.assertFailedWith(self.latest().operation_key, 'WORKSPACE_PATH_UNSAFE')
                self.assertEqual(os.listdir(target), [], 'nothing was created through the junction')
        self.assertIs(di.paths.ensure, real_ensure)

    def test_a_file_where_the_workspace_goes_is_refused(self):
        real_admit = di.admit

        def planting(*args, **kwargs):
            admitted = real_admit(*args, **kwargs)
            Path(admitted.host_workspace).parent.mkdir(parents=True)
            Path(admitted.host_workspace).write_bytes(b'')
            return admitted
        server = FakeAgentServer()
        with mock.patch.object(di, 'admit', planting):
            self.refused_dispatch('WORKSPACE_PATH_UNSAFE', server)
        self.assertEqual(server.calls, [])
        self.assertFailedWith(self.only().operation_key, 'WORKSPACE_PATH_UNSAFE')

    def test_a_failed_precondition_refuses_the_create(self):
        for precondition, cases in PRECONDITION_CASES.items():
            for name, answer in cases.items():
                with self.subTest(precondition=precondition, case=name):
                    server = FakeAgentServer(info=answer)
                    refusal = self.refused_dispatch('SERVER_PRECONDITION_FAILED', server)
                    self.assertIn(precondition, refusal.context['failed'])
                    self.assertEqual(server.calls, [('GET', '/server_info', None)], 'the create is never sent')
                    key = self.latest().operation_key
                    self.assertEqual(self.store.attempts(['reserved', 'dispatched', 'unknown', 'confirmed']), [])
                    self.assertFailedWith(key, 'SERVER_PRECONDITION_FAILED')
                    self.assertIs(json.loads(self.last_event(key).detail_json)['create_sent'], False)

    def test_an_unanswered_server_info_refuses_the_create(self):
        server = FakeAgentServer(info_error=ConnectionError('no route'))
        refusal = self.refused_dispatch('SERVER_PRECONDITION_FAILED', server)
        self.assertEqual(refusal.context['failed'], list(di.PRECONDITIONS))
        self.assertEqual(server.calls, [('GET', '/server_info', None)])
        self.assertFailedWith(self.only().operation_key, 'SERVER_PRECONDITION_FAILED')

    def test_server_info_not_allowlisted_refuses_before_any_call(self):
        def not_used(data):
            entry(data, *INFO)['dispatcher'] = 'not-used'
        manifest = self.approve_variant(routes=routes_variant(not_used))
        server = FakeAgentServer()
        self.refused_dispatch('ROUTE_NOT_ALLOWLISTED', server, manifest=manifest)
        self.assertEqual(server.calls, [])
        self.assertFailedWith(self.only().operation_key, 'ROUTE_NOT_ALLOWLISTED')

    def test_admitted_allowlist_bytes_are_pinned(self):
        """An admitted request whose route allowlist was swapped after admission is refused by
        send_create before any call, even when the swapped allowlist would allow everything."""
        def everything(data):
            for route in data['routes']:
                route['dispatcher'] = 'allowed'
        manifest, resolved, admitted = self.admitted()
        server = FakeAgentServer()
        for routes in (routes_variant(everything), b'', ROUTES_BYTES + b' '):
            with self.subTest(size=len(routes)), self.assertRaises(di.DispatchRefused) as caught:
                di.send_create(dataclasses.replace(admitted, routes_bytes=routes), resolved=resolved,
                               workspaces=self.workspaces, transport=server)
            self.assertEqual(caught.exception.code, 'PROFILE_ARTIFACT_DRIFTED')
        self.assertEqual(server.calls, [])

    # -- the answer -------------------------------------------------------------

    def test_a_4xx_is_a_refusal_and_the_attempt_failed(self):
        server = FakeAgentServer(create={'status': 422, 'body': {'detail': 'conversation_runtime'}})
        refusal = self.refused_dispatch('CREATE_REFUSED', server)
        self.assertEqual(refusal.context['status'], 422)
        self.assertEqual(len(server.creates), 1)
        key = self.only().operation_key
        self.assertFailedWith(key, 'CREATE_REFUSED')
        self.assertIs(json.loads(self.last_event(key).detail_json)['create_sent'], True)

    def test_an_uncertain_outcome_is_unknown_and_never_retried(self):
        other = dict(CREATE_ANSWER, body={**CREATE_ANSWER['body'], 'id': '00000000-0000-4000-8000-000000000000'})
        cases = {'500': {'create': {'status': 500, 'body': None}}, '202': {'create': {'status': 202, 'body': {}}},
                 'another conversation': {'create': other}}
        for name, kwargs in cases.items():
            with self.subTest(name):
                server = FakeAgentServer(**kwargs)
                with self.assertRaises(di.CreateOutcomeUnknown):
                    self.run_dispatch(server)
                self.assertEqual(len(server.creates), 1)
                unknown = self.only(['unknown'])
                self.assertEqual((unknown.reconciliation_status, self.last_event(unknown.operation_key).reason),
                                 ('required', 'create-outcome-uncertain'))
                self.assertNotIn('00000000-0000-4000-8000-000000000000', self.store.canonical_dump().decode())
                # An unknown outcome blocks the next attempt until it is reconciled (store contract).
                self.store.transition(unknown.operation_key, 'failed', actor='dispatch-test', reason='reconciled')

    def test_a_lost_answer_is_unknown_and_re_raised(self):
        server = FakeAgentServer(create_error=TimeoutError('no answer'))
        with self.assertRaises(TimeoutError):
            self.run_dispatch(server)
        self.assertEqual(len(server.creates), 1)
        unknown = self.only(['unknown'])
        self.assertEqual(self.last_event(unknown.operation_key).reason, 'create-unanswered')
        with self.assertRaises(store_mod.LiveClaim):  # no second conversation while it is unknown
            self.run_dispatch(FakeAgentServer())

    # -- outcomeRef ------------------------------------------------------------

    def test_every_reservation_carries_work_and_outcome_references(self):
        """A Work without exactly one well-formed outcome reference is refused before anything is
        reserved; the resolved intent always carries both keys."""
        outcome2 = 'outcome:6d0b7f0e-1c2a-4b8e-9f3d-2a7c5e4b1f90'
        refs = self.task2_references()
        cases = {
            'no outcome reference': ('OUTCOME_REF_ABSENT', {'outcome': None}),
            'the readable example form': ('OUTCOME_REF_INVALID', {'references': {'TASK-2': refs + ['outcome:O-101']}}),
            'upper case': ('OUTCOME_REF_INVALID', {'references': {'TASK-2': refs + [base.OUTCOME_REF.upper()
                                                                                   .replace('OUTCOME:', 'outcome:')]}}),
            'a symbolic revision': ('OUTCOME_REF_INVALID', {'references': {'TASK-2': refs + [base.OUTCOME_REF + '@HEAD']}}),
            'two outcomes': ('OUTCOME_REF_AMBIGUOUS', {'references': {'TASK-2': refs + [base.OUTCOME_REF, outcome2]}}),
            'one outcome at two revisions': ('OUTCOME_REF_AMBIGUOUS', {'references': {'TASK-2': refs + [
                base.OUTCOME_REF, f'{base.OUTCOME_REF}@{self.commit}']}}),
        }
        for name, (code, kwargs) in cases.items():
            with self.subTest(name):
                server = FakeAgentServer()
                self.refused_dispatch(code, server, sources=self.source_with(**kwargs))
                self.assertEqual((server.calls, self.store.attempts()), ([], []))
        pinned = f'{base.OUTCOME_REF}@{self.commit}'
        resolved = self.resolve(sources=self.source_with(references={'TASK-2': refs + [pinned, pinned]}))
        self.assertEqual((resolved.outcome_ref, resolved.intent()['outcomeRef'], resolved.intent()['workRef']),
                         (pinned, pinned, 'backlog:TASK-2'))
        self.assertEqual(set(self.resolve().intent()), {di.INTENT_KEY, 'workRef', 'outcomeRef'})


if __name__ == '__main__':
    unittest.main()
