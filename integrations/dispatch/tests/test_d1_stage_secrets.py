"""Tests for the D1 stage's create secrets: the attempt's inference token and endpoint (plan leaf E-05.6), offline.

Run from the repository root:

    python -I -B -m unittest discover -s integrations/dispatch/tests -p test_d1_stage_secrets.py -v

The proof, clause by clause:

* For the D1 stage, E-01.2.2's admission (``admit``, then ``admit_secrets``) accepts a create whose secrets block
  holds exactly the pinned registry entry's two names, each a StaticSecret, ``secrets_encrypted`` false: the
  attempt token, bound to the reserved conversation and attempt, and the profile's guest inference endpoint
  (``Accepts``).
* Every other shape is refused with a stable code at admission (the admission validator ``check_create_body``
  with the stage's secrets, and ``admit_secrets`` for the binding) and again by ``send_create`` before the
  transport, which is then called zero times (``Refusals``).
* Every other stage still refuses secrets (BODY_FIELD_UNKNOWN), and the S-03.3 qualification fixture is still
  refused for a real stage (``Refusals``; also test_d1_stage_admission.py).
* The check is one shared with S-03.3's qualification admission, not a copy (``SharedCheck``).
* The token is requested only after the reservation and every other input are admitted (``Issuance``); once
  issued it is revoked on a refusal or failure and at the attempt's end through the broker's control listener,
  shown by the grant's state (``Revocation``).
* No store record, admitted-create record, report or log carries the token, only its fingerprint (``Custody``).
* The dispatcher reads no provider credential, shown by a negative control (``NoProviderCredential``).

The broker is the real one (integrations/inference/inference_broker.py), in process, its control and inference
listeners on 127.0.0.1 with ephemeral ports, a synthetic provider key and an upstream that is never contacted
(issue, status and revoke only). The Agent Server is the E-01.3.1 fake replaying the pinned server's answers.
Everything else is the E-01.2.1 fixture in throwaway directories. No guest, provider, model or credential store is
used.
"""
from pathlib import Path
import ast
import contextlib
import copy
import dataclasses
import importlib.util
import io
import itertools
import json
import logging
import os
import pickle
import sys
import unittest
from unittest import mock
import uuid

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


d1 = _load('test_d1_stage_admission', HERE / 'test_d1_stage_admission.py')
cc = _load('test_conversation_create', HERE / 'test_conversation_create.py')
adm, base, di, store_mod, S = d1.adm, d1.base, d1.di, d1.store_mod, d1.S
aq, ic = di._inference_modules()
cs = di.secrets_check
SERVER_INFO = cc.SERVER_INFO
TOKEN_NAME, ENDPOINT_NAME = 'ANTHROPIC_API_KEY', 'ANTHROPIC_BASE_URL'
ENDPOINT = d1.ENDPOINT
PROVIDER_KEY = 'sk-ant-api03-' + 'x' * 40 + '-synthetic'
OTHER_TOKEN = 'aieh-inf-' + 'z' * 43
REVOKER = d1.REVOKER


class SpyControl:
    """The broker's ControlClient, observed: every issue and revoke is recorded (the issued tokens are kept by the
    test, for the custody search only). ISSUE_ARGS may alter an issue's arguments, ON_ISSUE runs after it, and a
    revoke raises REVOKE_ERROR when one is set."""

    def __init__(self, control, *, issue_args=None, on_issue=None, revoke_error=None):
        self.control, self.issue_args, self.on_issue, self.revoke_error = control, issue_args, on_issue, revoke_error
        self.issued, self.revoked, self.events = [], [], []

    def issue(self, *args):
        args = list(args) if self.issue_args is None else self.issue_args(list(args))
        self.events.append('issue')
        answer = self.control.issue(*args)
        self.issued.append(answer['token'])
        if self.on_issue is not None:
            self.on_issue(answer)
        return answer

    def revoke(self, fingerprint, trigger, revoker):
        self.revoked.append((fingerprint, trigger, revoker))
        if self.revoke_error is not None:
            raise self.revoke_error
        return self.control.revoke(fingerprint, trigger, revoker)


class SecretsFixture(d1.D1Fixture):
    """The E-05.2 D1 fixture (strong-d1-profile's implement stage is the D1 stage), with full dispatches. The
    broker's random token bodies are replaced by distinct fixed ones (digits only), so that no case depends on what
    a random body happens to contain (a provider-key-like run, or a word that picks another refusal code)."""

    def setUp(self):
        super().setUp()
        bodies = itertools.count(1)
        self.enterContext(mock.patch.object(S.IB.secrets, 'token_urlsafe', lambda n=32: f'{next(bodies):043d}'))

    def spy(self, rig='broker', **kwargs):
        return SpyControl(self.control(rig), **kwargs)

    def access_for(self, control):
        return di.InferenceAccess(control=control, revoker=REVOKER)

    def run_dispatch(self, transport, control=None, manifest=None, request=None, **kwargs):
        return di.dispatch(self.d1_request() if request is None else request,
                           manifest=manifest or self.approve_d1(), work_sources=self.d1_sources.get,
                           integration_store=self.store, workspaces=self.workspaces, transport=transport,
                           actor='e-05.6-test', read_profile=self.read_profile, read_artifact=self.read_artifact,
                           inference=None if control is None else self.access_for(control), **kwargs)

    def only(self, states=None):
        attempts = self.store.attempts(states)
        self.assertEqual(len(attempts), 1, attempts)
        return attempts[0]

    def detail(self, key, to_state):
        events = [e for e in self.store.events(key) if e.to_state == to_state]
        self.assertEqual(len(events), 1)
        return json.loads(events[0].detail_json)

    def grant_state(self, fingerprint, rig='broker'):
        return self.control(rig).grant(fingerprint)

    def assertRevoked(self, fingerprint, rig='broker'):
        state = self.grant_state(fingerprint, rig)
        self.assertEqual((state['state'], state['revocation']['trigger'], state['revocation']['revoker']),
                         ('revoked', 'attempt end', REVOKER))
        return state

    def assertNoGrant(self, rig='broker'):
        self.assertEqual(self.control(rig).status()['grants'], {'live': 0, 'revoked': 0, 'receipts_pending': 0})

    def reserved_pre(self, **changes):
        """A reserved D1 attempt and admit's create (every input but the secrets)."""
        manifest = self.approve_d1(**changes)
        resolved = self.resolve_d1(manifest)
        self.store.reserve_attempt(resolved.attempt_identity(), resolved.intent(), actor='d1-test')
        return manifest, resolved, self.admit(resolved, manifest)

    # -- the custody search -------------------------------------------------

    def dump(self, rig='broker'):
        held = store_mod.open_store(self.rig(rig).db)
        try:
            return held.canonical_dump().decode('utf-8')
        finally:
            held.close()

    def texts_of(self, *things):
        out = []
        for thing in things:
            if thing is None:
                continue
            if isinstance(thing, BaseException):
                out += [str(thing), repr(thing), '\n'.join(getattr(thing, '__notes__', []))]
                for name in ('to_json', 'context', 'detail'):
                    value = getattr(thing, name, None)
                    value = value() if callable(value) else value
                    out.append(json.dumps(value, sort_keys=True, default=repr))
            elif isinstance(thing, str):
                out.append(thing)
            else:
                out.append(json.dumps(thing, sort_keys=True, default=repr))
        return out

    def assertCustody(self, token, fingerprint, *things, recorded=True):
        """The token and its body after the prefix are in no store row (the dispatcher's and the broker's), no
        audit line and none of THINGS (records, exceptions, captured output); the fingerprint is in the
        dispatcher's store (when RECORDED: a failed store write records nothing)."""
        body = token[len('aieh-inf-'):]
        texts = [self.store.canonical_dump().decode('utf-8')]
        for name in self.rigs:
            texts += [self.dump(name), self.rigs[name].audit.path.read_text(encoding='utf-8')]
        texts += self.texts_of(*things)
        for text in texts:
            self.assertNotIn(token, text)
            self.assertNotIn(body, text)
        if recorded:
            self.assertIn(fingerprint, texts[0])

    @contextlib.contextmanager
    def captured(self):
        """Standard output, standard error and every log record while the block runs."""
        out, err, records = io.StringIO(), io.StringIO(), []

        class Keep(logging.Handler):
            def emit(self, record):
                records.append(self.format(record))
        handler, root = Keep(logging.DEBUG), logging.getLogger()
        level = root.level
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        box = {}
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                yield box
        finally:
            root.removeHandler(handler)
            root.setLevel(level)
            box['text'] = out.getvalue() + err.getvalue() + '\n'.join(records)


class SharedCheck(SecretsFixture):
    """One check, shared with S-03.3's qualification admission, not a copy."""

    def test_the_dispatcher_and_the_qualification_call_one_function(self):
        # One module, under one name, reached from both sides.
        self.assertIs(aq.secrets_check, cs)
        self.assertIs(sys.modules['aieh_dispatch_create_secrets'], cs)
        for code, meaning in cs.MEANINGS.items():
            with self.subTest(code=code):
                self.assertEqual(di.REFUSALS[code], meaning)
                if code != 'SECRET_TOKEN_NOT_BOUND':   # the qualification binds nothing
                    self.assertEqual(aq.REFUSALS[code], meaning)
        # Both calls reach the same function object.
        _, resolved, admitted = self.reserved_d1()
        qualification = aq.build_create(conversation_id=admitted.conversation_id, attempt_token=OTHER_TOKEN,
                                        acp_model=d1.TEST_MODEL, approved_models=[d1.TEST_MODEL],
                                        profile=json.loads(admitted.profile_bytes))
        with mock.patch.object(cs, 'check_secrets', wraps=cs.check_secrets) as spy:
            aq.check_create(qualification, conversation_id=admitted.conversation_id,
                            approved_models=[d1.TEST_MODEL], profile=json.loads(admitted.profile_bytes))
            self.send(admitted, resolved)
        self.assertEqual([call.kwargs['refused'] for call in spy.call_args_list],
                         [aq.QualificationRefused, di.DispatchRefused])
        self.assertIsNone(spy.call_args_list[0].kwargs.get('binding'))
        self.assertEqual(spy.call_args_list[1].kwargs['binding']['grant']['token_fingerprint'],
                         admitted.inference.fingerprint)
        # Whatever the one function refuses, both sides refuse with it: neither holds a copy of its own.
        self.transport = adm.CountingTransport()

        def refuse(body, *, refused, **kwargs):
            raise refused('SECRET_NAMES', 'the shared function refused')
        with mock.patch.object(cs, 'check_secrets', refuse):
            with self.assertRaises(aq.QualificationRefused) as caught:
                aq.check_create(qualification, conversation_id=admitted.conversation_id,
                                approved_models=[d1.TEST_MODEL], profile=json.loads(admitted.profile_bytes))
            self.assertEqual(caught.exception.detail, 'the shared function refused')
            refusal = self.assertDenied('SECRET_NAMES', self.send, admitted, resolved)
            self.assertEqual(refusal.detail, 'the shared function refused')
        # The provider-key needle is defined once, in the shared module.
        for module in ('dispatch_inputs.py', 'acp_qualification.py'):
            with self.subTest(module=module):
                self.assertNotIn("re.compile(r'sk-", (HERE.parent / module).read_text(encoding='utf-8'))
        self.assertIs(aq.PROVIDER_KEY_SHAPE, cs.PROVIDER_KEY_SHAPE)

    def test_importing_the_dispatcher_loads_no_inference_or_credential_module(self):
        """The D1 stage's inference modules are loaded on first use: the owner recorders' import census holds."""
        for module, expected in (('dispatch_inputs.py', ['integration_store', 'planning_readiness', 'aieh_paths',
                                                         'lineage', 'aieh_dispatch_create_secrets']),
                                 ('create_secrets.py', [])):
            with self.subTest(module=module):
                tree = ast.parse((HERE.parent / module).read_text(encoding='utf-8'))
                loads = [node.args[0].value for statement in tree.body if not isinstance(statement, (
                    ast.FunctionDef, ast.ClassDef)) for node in ast.walk(statement)
                    if isinstance(node, ast.Call) and getattr(node.func, 'id', None) == '_load']
                self.assertEqual(loads, expected)


class Accepts(SecretsFixture):
    def test_the_d1_create_carries_exactly_the_two_static_secrets(self):
        server, spy = cc.FakeAgentServer(), self.spy()
        result = self.run_dispatch(server, spy)
        attempt = self.only(['confirmed'])
        key = attempt.operation_key
        token = spy.issued[0]
        [(_, _, body)] = server.creates
        self.assertEqual(body['secrets'], {TOKEN_NAME: {'kind': 'StaticSecret', 'value': token},
                                           ENDPOINT_NAME: {'kind': 'StaticSecret', 'value': ENDPOINT}})
        self.assertIs(body['secrets_encrypted'], False)
        rest = {k: v for k, v in body.items() if k not in ('secrets', 'secrets_encrypted')}
        self.assertEqual(rest, dict(d1.TEST_TEMPLATE, conversation_id=attempt.conversation_id))
        # The token is the broker's grant for exactly this reserved conversation and attempt.
        fingerprint = ic.token_fingerprint(token)
        state = self.grant_state(fingerprint)
        self.assertEqual((state['state'], state['conversation_id'], state['attempt_id'], state['family'],
                          state['models'], state['budget']),
                         ('live', attempt.conversation_id, store_mod.attempt_id_for(key), 'anthropic-messages',
                          [d1.TEST_MODEL], {'requests': d1.GRANT['requests'], 'tokens': d1.GRANT['tokens']}))
        self.assertEqual(self.detail(key, 'dispatched')['inferenceGrant']['tokenFingerprint'], fingerprint)
        self.assertEqual(result.to_json()['inference_grant']['tokenFingerprint'], fingerprint)
        self.assertEqual(spy.issued, [token])
        self.assertEqual(spy.revoked, [])   # a confirmed attempt keeps its grant until its end

    def test_the_names_and_the_endpoint_come_from_the_registry_and_the_profile(self):
        _, resolved, pre = self.reserved_pre()
        staged = di.stage_inference(pre, resolved=resolved)
        self.assertEqual(staged.names, tuple(aq.registry_secret_names()))
        self.assertEqual(staged.names, (TOKEN_NAME, ENDPOINT_NAME))
        self.assertEqual(staged.endpoint, aq.inference_endpoint(json.loads(pre.profile_bytes)))
        self.assertEqual((staged.family, staged.models, staged.requests, staged.tokens, staged.ttl_s),
                         ('anthropic-messages', (d1.TEST_MODEL,), 10, 1000, 600))
        # The checked-in profile's endpoint is the same address (the synthetic profile mirrors it).
        real = json.loads((base.REPO / 'profiles' / 'strong-windows-qemu-whpx' / 'profile.json').read_bytes())
        self.assertEqual(aq.inference_endpoint(real), ENDPOINT)

    def test_the_access_takes_the_control_port_from_the_broker_configuration(self):
        access = di.InferenceAccess.from_component({'control_port': 47011, 'inference_port': 47012, 'families': {}},
                                                   revoker=REVOKER)
        self.assertIsInstance(access.control, ic.ControlClient)
        self.assertEqual((access.control.port, access.revoker), (47011, REVOKER))
        with self.assertRaises(ic.ControlError):
            di.InferenceAccess.from_component({'families': {}}, revoker=REVOKER)


class Refusals(SecretsFixture):
    """Each refusal at admission (the admission validator with the stage's secrets) and again at send_create,
    before the transport."""

    def body_cases(self, token):
        def secret(value, kind='StaticSecret'):
            return {'kind': kind, 'value': value}

        def put(path, value):
            def change(body):
                node = body
                for part in path[:-1]:
                    node = node[part]
                node[path[-1]] = value
            return change

        def drop(path):
            def change(body):
                node = body
                for part in path[:-1]:
                    node = node[part]
                del node[path[-1]]
            return change
        token_value, endpoint_value = ('secrets', TOKEN_NAME, 'value'), ('secrets', ENDPOINT_NAME, 'value')
        return [
            ('SECRET_NAMES', 'the token name missing', drop(('secrets', TOKEN_NAME))),
            ('SECRET_NAMES', 'the endpoint name missing', drop(('secrets', ENDPOINT_NAME))),
            ('SECRET_NAMES', 'an OH_ name added', put(('secrets', 'OH_SECRET_KEY'), secret('placeholder'))),
            ('SECRET_NAMES', 'a session key name added', put(('secrets', 'OH_SESSION_API_KEYS_0'), secret('x'))),
            ('SECRET_NAMES', 'another provider\'s name added', put(('secrets', 'OPENAI_API_KEY'), secret('x'))),
            ('SECRET_NAMES', 'an OAuth name added', put(('secrets', 'CLAUDE_CODE_OAUTH_TOKEN'), secret('x'))),
            ('SECRET_NAMES', 'a name in another case', lambda b: b['secrets'].__setitem__(
                'anthropic_api_key', b['secrets'].pop(TOKEN_NAME))),
            ('SECRET_NAMES', 'no secrets', put(('secrets',), {})),
            ('SECRET_NAMES', 'secrets null', put(('secrets',), None)),
            ('SECRET_NAMES', 'secrets a list', put(('secrets',), [TOKEN_NAME, ENDPOINT_NAME])),
            ('SECRET_NAMES', 'no secrets field', drop(('secrets',))),
            ('SECRET_KIND_FORBIDDEN', 'the token a LookupSecret', put(('secrets', TOKEN_NAME), {
                'kind': 'LookupSecret', 'url': ENDPOINT + '/token', 'headers': {}})),
            ('SECRET_KIND_FORBIDDEN', 'the endpoint a LookupSecret', put(('secrets', ENDPOINT_NAME),
                                                                         secret(ENDPOINT, 'LookupSecret'))),
            ('SECRET_KIND_FORBIDDEN', 'a description beside', put(('secrets', TOKEN_NAME, 'description'), 'd')),
            ('SECRET_KIND_FORBIDDEN', 'no kind', drop(('secrets', TOKEN_NAME, 'kind'))),
            ('SECRET_KIND_FORBIDDEN', 'a null value', put(endpoint_value, None)),
            ('SECRET_KIND_FORBIDDEN', 'a bare string', put(('secrets', ENDPOINT_NAME), ENDPOINT)),
            ('SECRETS_ENCRYPTED', 'secrets_encrypted true', put(('secrets_encrypted',), True)),
            ('SECRETS_ENCRYPTED', 'secrets_encrypted null', put(('secrets_encrypted',), None)),
            ('SECRETS_ENCRYPTED', 'secrets_encrypted "false"', put(('secrets_encrypted',), 'false')),
            ('SECRETS_ENCRYPTED', 'secrets_encrypted missing', drop(('secrets_encrypted',))),
            ('SECRET_PROVIDER_KEY_SHAPED', 'a provider key as the token', put(token_value, PROVIDER_KEY)),
            ('SECRET_PROVIDER_KEY_SHAPED', 'a provider key in a tag', put(('tags', 'aieh'), f'x {PROVIDER_KEY}')),
            ('SECRET_PROVIDER_KEY_SHAPED', 'a provider key as a tag key', put(('tags', PROVIDER_KEY), 'x')),
            ('SECRET_PROVIDER_KEY_SHAPED', 'a provider key in the endpoint', put(endpoint_value,
                                                                                 f'{ENDPOINT}/{PROVIDER_KEY}')),
            ('SECRET_PROVIDER_KEY_SHAPED', 'a provider key as the model', put(('agent_settings', 'acp_model'),
                                                                              'sk-proj-' + 'y' * 30)),
            ('SECRET_NOT_ATTEMPT_TOKEN', 'an empty token', put(token_value, '')),
            ('SECRET_NOT_ATTEMPT_TOKEN', 'a placeholder', put(token_value, 'placeholder')),
            ('SECRET_NOT_ATTEMPT_TOKEN', 'a token cut short', put(token_value, token[:-1])),
            ('SECRET_NOT_ATTEMPT_TOKEN', 'a token with more', put(token_value, token + 'a')),
            ('SECRET_NOT_ATTEMPT_TOKEN', 'a bearer header', put(token_value, 'Bearer ' + token)),
            ('TOKEN_OUTSIDE_SECRET', 'the token in a tag', put(('tags', 'aieh'), token)),
            ('TOKEN_OUTSIDE_SECRET', 'the token as a tag key', put(('tags', token), 'x')),
            ('TOKEN_OUTSIDE_SECRET', 'the token\'s body in a tag', put(('tags', 'aieh'), 'prefix' + token[9:])),
            ('TOKEN_OUTSIDE_SECRET', 'another token in a tag', put(('tags', 'aieh'), OTHER_TOKEN)),
            ('TOKEN_OUTSIDE_SECRET', 'the token in the endpoint', put(endpoint_value, f'{ENDPOINT}/{token}')),
            ('DESTINATION_NOT_ENDPOINT', 'the provider\'s origin', put(endpoint_value, 'https://api.anthropic.com')),
            ('DESTINATION_NOT_ENDPOINT', 'a path', put(endpoint_value, ENDPOINT + '/v1')),
            ('DESTINATION_NOT_ENDPOINT', 'a trailing slash', put(endpoint_value, ENDPOINT + '/')),
            ('DESTINATION_NOT_ENDPOINT', 'the host loopback', put(endpoint_value, 'http://127.0.0.1:8090')),
            ('DESTINATION_NOT_ENDPOINT', 'another port', put(endpoint_value, 'http://172.17.0.1:8091')),
            ('DESTINATION_NOT_ENDPOINT', 'another case', put(endpoint_value, 'HTTP://172.17.0.1:8090')),
            ('DESTINATION_NOT_ENDPOINT', 'an empty endpoint', put(endpoint_value, '')),
            ('DESTINATION_NOT_ENDPOINT', 'a destination in a tag', put(('tags', 'aieh'), 'http://198.51.100.7/')),
        ]

    def test_every_other_secrets_block_is_refused_at_admission_and_at_send(self):
        _, resolved, admitted = self.reserved_d1()
        token, grant = admitted.inference.token(), admitted.inference
        staged = self.staged(admitted, resolved)
        template = json.loads(admitted.template_bytes)
        admission = resolved.policy_inputs['admission']
        cases = self.body_cases(token)
        self.assertEqual({code for code, _, _ in cases} | {'SECRET_TOKEN_NOT_BOUND'}, set(cs.MEANINGS))
        for code, name, change in cases:
            with self.subTest(code=code, case=name):
                body = self.body_for(resolved, d1.TEST_TEMPLATE)
                change(body)
                with self.assertRaises(di.DispatchRefused) as caught:   # at admission
                    di.check_create_body(di._wire_body(body, staged, grant), admission=admission, template=template,
                                         conversation_id=admitted.conversation_id,
                                         secrets=staged.secrets(grant, admitted.operation_key))
                self.assertEqual(caught.exception.code, code, caught.exception.detail)
                refusal = self.assertDenied(code, self.send, self.tampered(admitted, body), resolved)  # at the send
                for text in self.texts_of(refusal):
                    self.assertNotIn(token, text)
                    self.assertNotIn(token[9:], text)
                    self.assertNotIn(PROVIDER_KEY, text)
        # The positive control on the same admitted create: it is sent, once.
        self.send(admitted, resolved)
        self.assertEqual(len(self.transport.calls), 1)

    def test_a_token_bound_to_another_conversation_or_attempt_is_refused(self):
        manifest, resolved, pre = self.reserved_pre()
        key = pre.operation_key
        wrong = {
            'another conversation': self.issue_for(resolved, conversation_id=str(uuid.uuid4()), rig='other'),
            'another attempt': self.issue_for(resolved, attempt_id=str(uuid.uuid4()), rig='other'),
        }
        good = self.issue_for(resolved)
        wrong['the token another grant\'s'] = di.InferenceGrant(
            token=wrong['another attempt'].token(), fingerprint=good.fingerprint, conversation_id=good.conversation_id,
            attempt_id=good.attempt_id, family=good.family, models=good.models, budget=good.budget,
            expires_at=good.expires_at)
        self.assertEqual((good.conversation_id, good.attempt_id),
                         (store_mod.conversation_id_for(key), store_mod.attempt_id_for(key)))
        for name, grant in wrong.items():
            with self.subTest(at='admission', case=name):
                refusal = self.assertDenied('SECRET_TOKEN_NOT_BOUND', di.admit_secrets, pre, resolved=resolved,
                                            workspaces=self.workspaces, grant=grant)
                self.assertNotIn(grant.token(), str(refusal) + json.dumps(refusal.to_json()))
        admitted = self.secreted(resolved, pre, good)
        for name, grant in wrong.items():
            with self.subTest(at='send', case=name):
                self.assertDenied('SECRET_TOKEN_NOT_BOUND', self.send, dataclasses.replace(admitted, inference=grant),
                                  resolved)
        with self.subTest(at='send', case='no grant held'):
            self.assertDenied('SECRET_NOT_ATTEMPT_TOKEN', self.send, dataclasses.replace(admitted, inference=None),
                              resolved)
            literal = self.wire(self.body_for(resolved, d1.TEST_TEMPLATE), admitted)   # the token, no grant
            refusal = self.assertDenied('SECRET_TOKEN_NOT_BOUND', self.send,
                                        dataclasses.replace(self.tampered(admitted, literal), inference=None), resolved)
            self.assertEqual(refusal.detail, 'no grant is held for this attempt')
        self.send(admitted, resolved)
        self.assertEqual(len(self.transport.calls), 1)

    def test_a_d1_create_without_its_secrets_is_refused_at_send(self):
        _, resolved, pre = self.reserved_pre()
        self.assertNotIn('secrets', pre.body)
        refusal = self.assertDenied('SECRET_NAMES', self.send, pre, resolved)
        self.assertIn(TOKEN_NAME, refusal.detail)
        # A grant on a create that admit_secrets did not build: its body has no secrets block either.
        self.assertDenied('SECRET_NAMES', self.send, dataclasses.replace(pre, inference=self.issue_for(resolved)),
                          resolved)

    def test_every_other_stage_still_refuses_secrets(self):
        manifest = self.approve_d1()
        grant = self.issue_for(self.resolve_d1(manifest))
        others = {
            'the D1 profile\'s review stage': (self.d1_request(repository='other-app', stage='review',
                                                               catalog_pin='reviewer-pin'), self.d1_sources),
            'a profile without the declaration': (self.request(), None),
        }
        for name, (request, sources) in others.items():
            with self.subTest(name):
                resolved = self.resolve(request, manifest, sources)
                self.store.reserve_attempt(resolved.attempt_identity(), resolved.intent(), actor='d1-test')
                admitted = self.admit(resolved, manifest)
                self.assertIsNone(di.stage_inference(admitted, resolved=resolved))
                for field, value in (('secrets', {TOKEN_NAME: {'kind': 'StaticSecret', 'value': grant.token()},
                                                  ENDPOINT_NAME: {'kind': 'StaticSecret', 'value': ENDPOINT}}),
                                     ('secrets_encrypted', False)):
                    body = dict(admitted.body, **{field: value})
                    refusal = self.assertDenied('BODY_FIELD_UNKNOWN', self.send, self.tampered(admitted, body), resolved)
                    self.assertEqual(refusal.context['field'], field)
                    with self.assertRaises(di.DispatchRefused) as caught:
                        di.check_create_body(body, admission=resolved.policy_inputs['admission'],
                                             template=json.loads(admitted.template_bytes),
                                             conversation_id=admitted.conversation_id)
                    self.assertEqual(caught.exception.code, 'BODY_FIELD_UNKNOWN')
                self.assertDenied('ADMISSION_MISMATCH', di.admit_secrets, admitted, resolved=resolved,
                                  workspaces=self.workspaces, grant=grant)
                self.assertDenied('ADMISSION_MISMATCH', self.send, dataclasses.replace(admitted, inference=grant),
                                  resolved)
                self.fail_live()

    def test_another_stage_s_dispatch_takes_no_token(self):
        spy = self.spy()
        result = self.run_dispatch(cc.FakeAgentServer(), spy, request=self.d1_request(
            repository='other-app', stage='review', catalog_pin='reviewer-pin'))
        self.assertEqual((spy.events, spy.revoked), ([], []))
        self.assertNotIn('inference_grant', result.to_json())
        self.assertNotIn('inferenceGrant', self.detail(result.operation_key, 'dispatched'))
        self.assertIsNone(di.end_attempt(self.store, result.operation_key, inference=self.access_for(spy),
                                         actor='e-05.6-test'))
        self.assertNoGrant()

    def test_a_template_carrying_secrets_is_refused(self):
        for field, value in (('secrets', {TOKEN_NAME: {'kind': 'StaticSecret', 'value': '{attempt_token}'},
                                          ENDPOINT_NAME: {'kind': 'StaticSecret', 'value': ENDPOINT}}),
                             ('secrets_encrypted', False)):
            with self.subTest(field):
                manifest = self.approve_d1(d1.as_bytes(dict(d1.TEST_TEMPLATE, **{field: value})))
                refusal = self.assertDenied('BODY_FIELD_UNKNOWN', self.admit, self.resolve_d1(manifest), manifest)
                self.assertEqual(refusal.context['field'], field)

    def test_the_inference_inputs_are_admitted_before_any_token(self):
        def endpoints(*entries):
            return lambda declared: declared.__setitem__('network', {'endpoints': list(entries)})
        other = dict(d1.INFERENCE_ENDPOINT, guest_port=8091)
        cases = {
            'no inference endpoint': dict(change=endpoints()),
            'two inference endpoints': dict(change=endpoints(d1.INFERENCE_ENDPOINT, other)),
            'an endpoint without a port': dict(change=endpoints({'class': 'inference', 'guest_address': '172.17.0.1'})),
            'an endpoint by name': dict(change=endpoints(dict(d1.INFERENCE_ENDPOINT,
                                                              guest_address='host.docker.internal'))),
            'another ACP server': dict(template=d1.candidate_with(
                lambda body: body['agent_settings'].update(acp_server='codex', acp_model=d1.TEST_MODEL))),
            'a wildcard model': dict(template=d1.candidate_with(
                lambda body: body['agent_settings'].update(acp_model='syn-model-*'))),
            'a model with a space': dict(template=d1.candidate_with(
                lambda body: body['agent_settings'].update(acp_model='syn model'))),
        }
        for name, changes in cases.items():
            with self.subTest(name):
                manifest = self.approve_d1(**changes)
                self.assertDenied('INFERENCE_INPUTS_INVALID', self.admit, self.resolve_d1(manifest), manifest)
        with self.subTest('the registry extract drifted'), mock.patch.object(aq, 'REGISTRY_SHA256', '0' * 64):
            manifest = self.approve_d1()
            refusal = self.assertDenied('INFERENCE_INPUTS_INVALID', self.admit, self.resolve_d1(manifest), manifest)
            self.assertIn('FIXTURE_DRIFTED', refusal.detail)

    def test_the_grant_declaration_is_required_at_resolution(self):
        def without(declared):
            del declared['provisioning']['agent_server'][di.STAGE_TEMPLATE_KEY][di.GRANT_KEY]
        good = dict(d1.GRANT)
        cases = {
            'missing': dict(change=without),
            'not an object': dict(grant=[10, 1000, 600]),
            'a key missing': dict(grant={k: v for k, v in good.items() if k != 'ttl_s'}),
            'a key more': dict(grant=dict(good, cost=1)),
            'zero requests': dict(grant=dict(good, requests=0)),
            'negative tokens': dict(grant=dict(good, tokens=-1)),
            'a boolean': dict(grant=dict(good, requests=True)),
            'a float': dict(grant=dict(good, ttl_s=600.0)),
            'a string': dict(grant=dict(good, tokens='1000')),
        }
        for name, case in cases.items():
            with self.subTest(name):
                pin = {'stage': 'implement', 'path': d1.D1_PATH, 'sha256': d1.sha(d1.TEST_TEMPLATE_BYTES)}
                if 'grant' in case:
                    pin[di.GRANT_KEY] = case['grant']
                manifest = self.approve_d1(pin=pin, change=case.get('change'))
                self.assertRefused('PROFILE_ADMISSION_INVALID', self.d1_request(), manifest, self.d1_sources)
                self.assertRefused('PROFILE_ADMISSION_INVALID', self.d1_request(
                    repository='other-app', stage='review', catalog_pin='reviewer-pin'), manifest, self.d1_sources)


class Issuance(SecretsFixture):
    def test_the_token_is_requested_only_after_the_reservation_and_every_other_input(self):
        order, seen = [], {}
        names = ('admit', 'stage_inference', 'admit_secrets', 'create_workspace', 'send_create')
        real = {name: getattr(di, name) for name in names}

        def spying(name):
            def wrapper(*args, **kwargs):
                order.append(name)
                return real[name](*args, **kwargs)
            return wrapper

        def on_issue(answer):
            order.append('issue')
            seen['states'] = [a.state for a in self.store.attempts()]
            seen['workspace'] = os.path.lexists(self.category)
        spy = self.spy(on_issue=on_issue)
        with mock.patch.multiple(di, **{name: spying(name) for name in names}):
            self.run_dispatch(cc.FakeAgentServer(), spy)
        self.assertEqual(order, ['admit', 'stage_inference', 'issue', 'admit_secrets', 'create_workspace',
                                 'send_create'])
        self.assertEqual(seen, {'states': ['reserved'], 'workspace': False})

    def test_a_refusal_before_the_issue_issues_nothing(self):
        cases = {
            'INFERENCE_INPUTS_INVALID': dict(manifest=lambda: self.approve_d1(
                change=lambda declared: declared.__setitem__('network', {'endpoints': []}))),
            'PROFILE_ARTIFACT_DRIFTED': dict(manifest=self.drifted),
            'INFERENCE_GRANT_UNAVAILABLE': dict(control=None),
        }
        for code, case in cases.items():
            with self.subTest(code):
                spy = self.spy()
                manifest = case.get('manifest', self.approve_d1)()
                server = cc.FakeAgentServer()
                with self.assertRaises(di.DispatchRefused) as caught:
                    self.run_dispatch(server, case.get('control', spy), manifest=manifest)
                self.assertEqual(caught.exception.code, code, caught.exception.detail)
                attempt = self.latest_failed()
                detail = self.detail(attempt.operation_key, 'failed')
                self.assertEqual(detail['code'], code)
                self.assertNotIn('inference_grant', detail['context'])
                self.assertEqual((spy.events, server.calls), ([], []))
                self.assertNoGrant()

    def test_a_grant_the_broker_refuses_is_a_refused_attempt(self):
        """The template's model is not in the broker's allowlist: the broker issues nothing."""
        spy = self.spy()
        manifest = self.approve_d1(d1.candidate_with(
            lambda body: body['agent_settings'].update(acp_model='syn-unlisted')))
        with self.assertRaises(di.DispatchRefused) as caught:
            self.run_dispatch(cc.FakeAgentServer(), spy, manifest=manifest)
        self.assertEqual((caught.exception.code, caught.exception.context['broker_code']),
                         ('INFERENCE_GRANT_UNAVAILABLE', 'MODEL_NOT_ALLOWLISTED'))
        self.assertEqual(self.detail(self.only(['failed']).operation_key, 'failed')['code'],
                         'INFERENCE_GRANT_UNAVAILABLE')
        self.assertEqual((spy.events, spy.issued), (['issue'], []))
        self.assertNoGrant()

    def drifted(self):
        manifest = self.approve_d1()
        (self.profiles / d1.D1 / 'agent-server' / 'd1-create.json').write_bytes(d1.CANDIDATE_BYTES)
        return manifest

    def latest_failed(self):
        return max(self.store.attempts(['failed']),
                   key=lambda r: self.store.attempt_identity(r.operation_key).identity.ordinal)


class Revocation(SecretsFixture):
    """Once issued, the grant is revoked on every refusal or failure (before the attempt's outcome is recorded)
    and at the attempt's end, through the broker's control listener: the grant's state shows it."""

    def failed_dispatch(self, transport, spy, expected, to_state, recorded=True):
        with self.captured() as out:
            with self.assertRaises(expected) as caught:
                self.run_dispatch(transport, spy)
        attempt = self.only([to_state])
        token = spy.issued[0]
        fingerprint = ic.token_fingerprint(token)
        state = self.assertRevoked(fingerprint)
        self.assertEqual(spy.revoked, [(fingerprint, 'attempt end', REVOKER)])
        self.assertCustody(token, fingerprint, caught.exception, out['text'], recorded=recorded)
        return caught.exception, attempt, fingerprint, state

    def assertRecorded(self, refusal, attempt, fingerprint):
        detail = self.detail(attempt.operation_key, attempt.state)
        for revocation in (refusal.context['inference_revocation'], detail['context']['inference_revocation']):
            self.assertEqual((revocation['tokenFingerprint'], revocation['revoked'], revocation['trigger'],
                              revocation['revoker'], revocation['attemptId']),
                             (fingerprint, True, 'attempt end', REVOKER, store_mod.attempt_id_for(attempt.operation_key)))
        self.assertEqual(detail['context']['inference_grant']['tokenFingerprint'], fingerprint)

    def test_revoked_when_the_secrets_admission_refuses(self):
        """The broker answers with a grant of another conversation: admit_secrets refuses it, and it is revoked."""
        def elsewhere(args):
            args[0] = str(uuid.uuid4())
            return args
        spy = self.spy(issue_args=elsewhere)
        refusal, attempt, fingerprint, _ = self.failed_dispatch(cc.FakeAgentServer(), spy, di.DispatchRefused, 'failed')
        self.assertEqual(refusal.code, 'SECRET_TOKEN_NOT_BOUND')
        self.assertRecorded(refusal, attempt, fingerprint)

    def test_revoked_when_the_workspace_refuses(self):
        """A file planted where the workspace goes, after admission and the issue."""
        def plant(answer):
            self.category.mkdir(parents=True, exist_ok=True)
            (self.category / 'demo-app').write_bytes(b'not a directory')
        spy = self.spy(on_issue=plant)
        server = cc.FakeAgentServer()
        refusal, attempt, fingerprint, _ = self.failed_dispatch(server, spy, di.DispatchRefused, 'failed')
        self.assertEqual((refusal.code, server.calls), ('WORKSPACE_PATH_UNSAFE', []))
        self.assertRecorded(refusal, attempt, fingerprint)

    def test_revoked_when_the_dispatched_transition_fails(self):
        transition = self.store.transition

        def failing(key, to_state, **kwargs):
            if to_state == 'dispatched':
                raise store_mod.StoreError('synthetic store failure')
            return transition(key, to_state, **kwargs)
        spy = self.spy()
        with mock.patch.object(self.store, 'transition', failing):
            error, attempt, fingerprint, _ = self.failed_dispatch(cc.FakeAgentServer(), spy, store_mod.StoreError,
                                                                  'reserved', recorded=False)
        self.assertIn(fingerprint, '\n'.join(error.__notes__))
        self.assertIn('"revoked":true', '\n'.join(error.__notes__))

    def test_revoked_when_send_create_refuses(self):
        server = cc.FakeAgentServer(info={'status': 200, 'body': {}})
        refusal, attempt, fingerprint, _ = self.failed_dispatch(server, self.spy(), di.DispatchRefused, 'failed')
        self.assertEqual((refusal.code, server.creates), ('SERVER_PRECONDITION_FAILED', []))
        self.assertIs(self.detail(attempt.operation_key, 'failed')['create_sent'], False)
        self.assertRecorded(refusal, attempt, fingerprint)

    def test_revoked_when_the_transport_fails(self):
        server = cc.FakeAgentServer(create_error=ConnectionResetError('synthetic: no answer'))
        error, attempt, fingerprint, _ = self.failed_dispatch(server, self.spy(), ConnectionResetError, 'unknown')
        detail = self.detail(attempt.operation_key, 'unknown')
        self.assertEqual((detail['inferenceGrant']['tokenFingerprint'], detail['inferenceRevocation']['revoked']),
                         (fingerprint, True))
        self.assertIn(fingerprint, '\n'.join(error.__notes__))

    def test_revoked_when_the_create_is_refused(self):
        server = cc.FakeAgentServer(create={'status': 409, 'body': {'detail': 'synthetic conflict'}})
        refusal, attempt, fingerprint, _ = self.failed_dispatch(server, self.spy(), di.DispatchRefused, 'failed')
        self.assertEqual(refusal.code, 'CREATE_REFUSED')
        self.assertIs(self.detail(attempt.operation_key, 'failed')['create_sent'], True)
        self.assertRecorded(refusal, attempt, fingerprint)

    def test_revoked_when_the_outcome_is_unknown(self):
        server = cc.FakeAgentServer(create={'status': 503, 'body': {}})
        error, attempt, fingerprint, _ = self.failed_dispatch(server, self.spy(), di.CreateOutcomeUnknown, 'unknown')
        self.assertEqual(error.context['inference_revocation']['revoked'], True)
        self.assertEqual(self.detail(attempt.operation_key, 'unknown')['inferenceRevocation']['tokenFingerprint'],
                         fingerprint)

    def test_a_confirmed_attempt_s_grant_is_revoked_at_its_end(self):
        spy = self.spy()
        with self.captured() as out:
            result = self.run_dispatch(cc.FakeAgentServer(), spy)
        token, key = spy.issued[0], result.operation_key
        fingerprint = ic.token_fingerprint(token)
        self.assertEqual(self.grant_state(fingerprint)['state'], 'live')
        access = self.access_for(spy)
        record = di.end_attempt(self.store, key, inference=access, actor='e-05.6-test')
        self.assertEqual((record['format'], record['tokenFingerprint'], record['revoked'], record['trigger'],
                          record['revoker'], record['attemptId']),
                         (di.REVOCATION_FORMAT, fingerprint, True, 'attempt end', REVOKER, result.attempt_id))
        self.assertRevoked(fingerprint)
        receipt_key = f'dispatch/attempt/{result.attempt_id}/inference-revocation/1'
        self.assertEqual(self.store.get(receipt_key).state, 'confirmed')
        self.assertEqual(json.loads(self.store.events(receipt_key)[-1].detail_json), record)
        # The broker's own receipt, by fingerprint, in its integration store.
        self.assertIn(f'inference/attempt/{result.attempt_id}/revocation', self.dump())
        # Again: the recorded revocation, without a second call.
        self.assertEqual(di.end_attempt(self.store, key, inference=access, actor='e-05.6-test'), record)
        self.assertEqual(len(spy.revoked), 1)
        self.assertCustody(token, fingerprint, result.to_json(), record, out['text'])

    def test_only_a_confirmed_attempt_is_ended(self):
        server = cc.FakeAgentServer(info={'status': 200, 'body': {}})
        spy = self.spy()
        with self.assertRaises(di.DispatchRefused):
            self.run_dispatch(server, spy)
        refusal = self.assertDenied('ATTEMPT_NOT_CONFIRMED', di.end_attempt, self.store,
                                    self.only(['failed']).operation_key, inference=self.access_for(spy),
                                    actor='e-05.6-test')
        self.assertEqual(refusal.context['state'], 'failed')
        self.assertEqual(len(spy.revoked), 1)   # the failure's revocation only

    def test_a_revocation_failure_is_recorded_and_surfaced(self):
        unreachable = ic.ControlError('CONTROL_UNREACHABLE', '127.0.0.1: synthetic')
        # On a failure path: the attempt's own outcome is still recorded, with the failed revocation.
        server = cc.FakeAgentServer(info={'status': 200, 'body': {}})
        spy = self.spy(revoke_error=unreachable)
        with self.assertRaises(di.DispatchRefused) as caught:
            self.run_dispatch(server, spy)
        fingerprint = ic.token_fingerprint(spy.issued[0])
        detail = self.detail(self.only(['failed']).operation_key, 'failed')
        for revocation in (caught.exception.context['inference_revocation'],
                           detail['context']['inference_revocation']):
            self.assertEqual((revocation['revoked'], revocation['code']), (False, 'CONTROL_UNREACHABLE'))
        self.assertEqual(caught.exception.code, 'SERVER_PRECONDITION_FAILED')
        self.assertEqual(self.grant_state(fingerprint)['state'], 'live')   # honestly: not revoked

    def test_a_revocation_failure_at_the_attempt_s_end_is_recorded_and_retried(self):
        spy = self.spy()
        result = self.run_dispatch(cc.FakeAgentServer(), spy)
        fingerprint = ic.token_fingerprint(spy.issued[0])
        failing = self.access_for(self.spy(revoke_error=ic.ControlError('CONTROL_UNREACHABLE', 'synthetic')))
        refusal = self.assertDenied('INFERENCE_REVOCATION_FAILED', di.end_attempt, self.store, result.operation_key,
                                    inference=failing, actor='e-05.6-test')
        self.assertEqual((refusal.context['inference_revocation']['revoked'],
                          refusal.context['inference_revocation']['code']), (False, 'CONTROL_UNREACHABLE'))
        first = f'dispatch/attempt/{result.attempt_id}/inference-revocation/1'
        self.assertEqual((self.store.get(first).state, self.store.events(first)[-1].reason),
                         ('failed', 'CONTROL_UNREACHABLE'))
        self.assertEqual(self.grant_state(fingerprint)['state'], 'live')
        record = di.end_attempt(self.store, result.operation_key, inference=self.access_for(spy), actor='e-05.6-test')
        self.assertTrue(record['revoked'])
        self.assertEqual(self.store.get(f'dispatch/attempt/{result.attempt_id}/inference-revocation/2').state,
                         'confirmed')
        self.assertRevoked(fingerprint)


class Custody(SecretsFixture):
    """No record carries the token: only its fingerprint (the success and failure paths assert it as well)."""

    def test_the_admitted_create_and_the_grant_carry_the_fingerprint_only(self):
        _, resolved, admitted = self.reserved_d1()
        token, fingerprint = admitted.inference.token(), admitted.inference.fingerprint
        record = admitted.to_json()
        self.assertEqual(record['body']['secrets'][TOKEN_NAME], {'kind': 'StaticSecret', 'value': di.TOKEN_SLOT})
        self.assertEqual(record['inference_grant']['tokenFingerprint'], fingerprint)
        self.assertEqual(fingerprint, ic.token_fingerprint(token))
        for text in (json.dumps(record), admitted.body_json, repr(admitted), str(admitted.inference),
                     json.dumps(admitted.inference.record())):
            self.assertNotIn(token, text)
            self.assertNotIn(token[9:], text)
        self.assertIn(fingerprint, repr(admitted))
        with self.assertRaises(TypeError):
            pickle.dumps(admitted.inference)
        admitted.inference.drop()
        with self.assertRaises(ValueError):
            admitted.inference.token()

    def test_a_refusal_never_echoes_the_token(self):
        _, resolved, admitted = self.reserved_d1()
        token = admitted.inference.token()
        cases = {
            'BODY_FIELD_UNKNOWN': lambda body: body.__setitem__(token, 'x'),
            'TOKEN_OUTSIDE_SECRET': lambda body: body['tags'].__setitem__(token, 'x'),
            'SECRET_PROVIDER_KEY_SHAPED': lambda body: body['tags'].__setitem__(PROVIDER_KEY, 'x'),
        }
        for code, change in cases.items():
            with self.subTest(code):
                body = self.body_for(resolved, d1.TEST_TEMPLATE)
                change(body)
                refusal = self.assertDenied(code, self.send, self.tampered(admitted, body), resolved)
                for text in self.texts_of(refusal):
                    for needle in (token, token[9:], PROVIDER_KEY):
                        self.assertNotIn(needle, text)
                self.assertIn('<', refusal.detail + json.dumps(refusal.context))   # redacted, not dropped

    def test_the_token_reaches_the_transport_only_in_the_create(self):
        server, spy = cc.FakeAgentServer(), self.spy()
        self.run_dispatch(server, spy)
        token = spy.issued[0]
        self.assertEqual([token in json.dumps(body) for _, _, body in server.calls], [False, True])


class NoProviderCredential(SecretsFixture):
    """Negative control: a provider key under the broker's credential entry and in the provider environment names;
    a full dispatch and its end read none of them, and the sentinel appears nowhere."""

    SENTINEL = 'sk-ant-api03-' + 'S' * 40 + '-sentinel'
    NAMES = ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_BASE_URL', 'CLAUDE_CODE_OAUTH_TOKEN',
             'OPENAI_API_KEY', 'AIEH_MODEL_PROVIDER_KEY')

    def test_the_dispatcher_reads_no_provider_credential(self):
        credentials = sys.modules['aieh_credential_provider']   # the broker's credential provider module
        held = S.MemoryProvider({S.IB.ENTRY: (S.PROVIDER, self.SENTINEL)})
        reads, environ_reads = [], []
        spy, server = self.spy(), cc.FakeAgentServer()
        self.rig()   # the broker, started before the spies: it holds a synthetic key, never read here
        real_getitem = type(os.environ).__getitem__

        def getitem(environ, name):
            environ_reads.append(name)
            return real_getitem(environ, name)

        def provider_get(provider, name):
            reads.append(name)
            return held.entries.get(name)
        with mock.patch.dict(os.environ, {name: self.SENTINEL for name in self.NAMES}), \
                mock.patch.object(type(os.environ), '__getitem__', getitem), \
                mock.patch.object(credentials, 'select_provider', side_effect=lambda *a, **k: reads.append('select')
                                  or held) as select, \
                mock.patch.object(credentials.WindowsCredentialProvider, 'get', provider_get), \
                mock.patch.object(credentials.KeyringProvider, 'get', provider_get), \
                mock.patch.object(S.MemoryProvider, 'get', provider_get):
            result = self.run_dispatch(server, spy)
            record = di.end_attempt(self.store, result.operation_key, inference=self.access_for(spy),
                                    actor='e-05.6-test')
            dispatched_reads = list(environ_reads)
            os.environ.get('ANTHROPIC_API_KEY')                  # the spies' positive controls
            credentials.select_provider().get(S.IB.ENTRY)
        self.assertEqual((select.call_count, reads), (1, ['select', S.IB.ENTRY]))   # only the controls' reads
        self.assertEqual(sorted(set(dispatched_reads) & set(self.NAMES)), [])
        self.assertIn('ANTHROPIC_API_KEY', environ_reads)
        texts = [json.dumps(server.calls), self.store.canonical_dump().decode('utf-8'), self.dump(),
                 json.dumps(result.to_json()), json.dumps(record)]
        for text in texts:
            self.assertNotIn(self.SENTINEL, text)
        self.assertNotIn(S.KEY, json.dumps(server.calls))   # nor the broker's own (synthetic) key


if __name__ == '__main__':
    unittest.main()
