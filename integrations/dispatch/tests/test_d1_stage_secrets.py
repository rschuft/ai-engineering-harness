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
import base64
import contextlib
import copy
import dataclasses
import hashlib
import importlib.util
import io
import itertools
import json
import logging
import os
import pickle
import sqlite3
import sys
import threading
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

    def revoke_attempt(self, conversation_id, attempt_id, trigger, revoker):
        self.revoked.append(((conversation_id, attempt_id), trigger, revoker))
        if self.revoke_error is not None:
            raise self.revoke_error
        return self.control.revoke_attempt(conversation_id, attempt_id, trigger, revoker)


class SecretsFixture(d1.D1Fixture):
    """The E-05.2 D1 fixture (strong-d1-profile's implement stage is the D1 stage), with full dispatches. The
    broker's random token bodies are replaced by distinct fixed ones (the URL-safe base64 of a counter's sha256), so
    that no case depends on what a random body happens to contain (a provider-key-like run, or a word that picks
    another refusal code)."""

    def setUp(self):
        super().setUp()
        bodies = itertools.count(1)

        def body(n=32):
            digest = hashlib.sha256(f'E-05.6 synthetic attempt token {next(bodies)}'.encode()).digest()
            return base64.urlsafe_b64encode(digest).decode('ascii').rstrip('=')
        self.enterContext(mock.patch.object(S.IB.secrets, 'token_urlsafe', body))

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

    def typed(self, states=None):
        """The typed dispatch attempts (not the grant journal or revocation receipts beside them)."""
        return [a for a in self.store.attempts(states) if a.operation_key.startswith('attempt/')]

    def only(self, states=None):
        attempts = self.typed(states)
        self.assertEqual(len(attempts), 1, [a.operation_key for a in attempts])
        return attempts[0]

    def journal(self, attempt_id):
        """The attempt's grant journal: its state and last detail."""
        key = f'dispatch/attempt/{attempt_id}/inference-grant'
        held = self.store.get(key)
        events = self.store.events(key)
        return held.state, json.loads(events[-1].detail_json or 'null')

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

    def crashed_after_the_issue(self):
        """The dispatcher issued and then stopped: the journal is dispatched, the attempt reserved, the grant live,
        and nothing of the dispatcher's handlers ran."""
        spy = self.spy()
        real = di._issue

        def issue_then_crash(*args, **kwargs):
            real(*args, **kwargs)
            raise Crash()
        with mock.patch.object(di, '_issue', issue_then_crash), \
                mock.patch.object(di._GrantCustody, 'needs_end', lambda custody: False), self.assertRaises(Crash):
            self.run_dispatch(cc.FakeAgentServer(), spy)
        key = self.only(['reserved']).operation_key
        self.assertEqual(self.journal(store_mod.attempt_id_for(key)), ('dispatched', None))
        fingerprint = ic.token_fingerprint(spy.issued[0])
        self.assertEqual(self.grant_state(fingerprint)['state'], 'live')
        return key, fingerprint

    # -- the custody search -------------------------------------------------

    def dump(self, rig='broker'):
        held = store_mod.open_store(self.rig(rig).db)
        try:
            return held.canonical_dump().decode('utf-8')
        finally:
            held.close()

    def texts_of(self, *things):
        """The texts of THINGS; an exception's with every exception of its __context__ and __cause__ chains."""
        out = []
        for thing in things:
            if thing is None:
                continue
            if isinstance(thing, BaseException):
                chain, seen = [thing], set()
                while chain:
                    exc = chain.pop()
                    if exc is None or id(exc) in seen:
                        continue
                    seen.add(id(exc))
                    out += [str(exc), repr(exc), '\n'.join(getattr(exc, '__notes__', []))]
                    for name in ('to_json', 'context', 'detail'):
                        value = getattr(exc, name, None)
                        value = value() if callable(value) else value
                        out.append(json.dumps(value, sort_keys=True, default=repr))
                    chain += [exc.__context__, exc.__cause__]
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

    def test_a_part_of_the_token_outside_its_secret_is_refused(self):
        """Any run of create_secrets.FRAGMENT (8) or more characters of the token's body outside its secret is
        TOKEN_OUTSIDE_SECRET at admission and at the send; 7 characters are not (refused only as not the template:
        the boundary is deliberate)."""
        _, resolved, admitted = self.reserved_d1()
        token, grant = admitted.inference.token(), admitted.inference
        staged, body_of = self.staged(admitted, resolved), token[9:]
        self.assertEqual(cs.FRAGMENT, 8)

        def at_admission(body):
            with self.assertRaises(di.DispatchRefused) as caught:
                di.check_create_body(di._wire_body(body, staged, grant), admission=resolved.policy_inputs['admission'],
                                     template=json.loads(admitted.template_bytes),
                                     conversation_id=admitted.conversation_id,
                                     secrets=staged.secrets(grant, admitted.operation_key))
            return caught.exception

        cases = {'start': body_of[:8], 'middle': body_of[17:25], 'end': body_of[-8:], 'longer': body_of[5:30]}
        for name, part in cases.items():
            for where in ('tag', 'tag key', 'endpoint path'):
                with self.subTest(part=name, where=where):
                    body = self.body_for(resolved, d1.TEST_TEMPLATE)
                    if where == 'tag':
                        body['tags']['aieh'] = 'x' + part + 'y'
                    elif where == 'tag key':
                        body['tags']['x' + part] = 'x'
                    else:
                        body['secrets'][ENDPOINT_NAME]['value'] = f'{ENDPOINT}/{part}'
                    self.assertEqual(at_admission(body).code, 'TOKEN_OUTSIDE_SECRET')
                    refusal = self.assertDenied('TOKEN_OUTSIDE_SECRET', self.send, self.tampered(admitted, body),
                                                resolved)
                    self.assertNotIn(part, ''.join(self.texts_of(refusal)))
        for name, part in {'start': body_of[:7], 'middle': body_of[17:24], 'end': body_of[-7:]}.items():
            with self.subTest(seven=name):
                body = self.body_for(resolved, d1.TEST_TEMPLATE)
                body['tags']['aieh'] = '.' + part + '.'   # not URL-safe: the run is exactly 7 characters
                self.assertEqual(at_admission(body).code, 'BODY_NOT_TEMPLATE')
                self.assertDenied('BODY_NOT_TEMPLATE', self.send, self.tampered(admitted, body), resolved)
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
            seen['states'] = [a.state for a in self.typed()]
            seen['workspace'] = os.path.lexists(self.category)
            # the issue was journaled before the call (E-05.6, R2): the journal is dispatched, without the token
            seen['journal'] = [(a.state, 'token' in a.intent_json) for a in self.store.attempts()
                               if a.operation_key.endswith('/inference-grant')]
        spy = self.spy(on_issue=on_issue)
        with mock.patch.multiple(di, **{name: spying(name) for name in names}):
            self.run_dispatch(cc.FakeAgentServer(), spy)
        self.assertEqual(order, ['admit', 'stage_inference', 'issue', 'admit_secrets', 'create_workspace',
                                 'send_create'])
        self.assertEqual(seen, {'states': ['reserved'], 'workspace': False, 'journal': [('dispatched', False)]})

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
            if to_state == 'dispatched' and key.startswith('attempt/'):   # the attempt's, not the journal's
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

    def test_ending_a_failed_attempt_returns_its_recorded_revocation(self):
        """A failed attempt's grant was revoked, and journaled, at its failure: end_attempt returns that record
        without a second call (ATTEMPT_NOT_ENDABLE is gone: an attempt with nothing to end is a no-op, None)."""
        server = cc.FakeAgentServer(info={'status': 200, 'body': {}})
        spy = self.spy()
        with self.assertRaises(di.DispatchRefused) as caught:
            self.run_dispatch(server, spy)
        record = di.end_attempt(self.store, self.only(['failed']).operation_key, inference=self.access_for(spy),
                                actor='e-05.6-test')
        self.assertEqual(record, caught.exception.context['inference_revocation'])
        self.assertEqual(len(spy.revoked), 1)   # the failure's revocation only
        self.assertNotIn('ATTEMPT_NOT_ENDABLE', di.REFUSALS)
        with self.assertRaises(di.DispatchRefused) as unknown:
            di.end_attempt(self.store, 'attempt/v1/TASK-9/x', inference=self.access_for(spy), actor='e-05.6-test')
        self.assertEqual(unknown.exception.code, 'RESERVATION_INVALID')

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
        # Review P2: the failed revocation is journaled, and a later end_attempt revokes the failed attempt's grant.
        key = self.only(['failed']).operation_key
        aid = store_mod.attempt_id_for(key)
        self.assertEqual(self.store.get(f'dispatch/attempt/{aid}/inference-revocation/1').state, 'failed')
        record = di.end_attempt(self.store, key, inference=self.access_for(self.spy()), actor='e-05.6-test')
        self.assertEqual((record['revoked'], record['tokenFingerprint']), (True, fingerprint))
        self.assertEqual(self.store.get(f'dispatch/attempt/{aid}/inference-revocation/2').state, 'confirmed')
        self.assertRevoked(fingerprint)

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


class Crash(BaseException):
    """The dispatcher process ending where it stands (no handler of it runs)."""


class GrantJournal(SecretsFixture):
    """Every issued grant can be found, revoked and retried (review R2 to R4): the issue is journaled before the
    call; a lost or invalid answer, any BaseException after the issue and a crashed dispatcher all end with the
    broker's grant revoked."""

    def assertAllRevoked(self, rig='broker'):
        grants = self.control(rig).status()['grants']
        self.assertEqual((grants['live'], grants['receipts_pending']), (0, 0))
        self.assertGreaterEqual(grants['revoked'], 1)

    def test_any_base_exception_after_the_issue_revokes_the_grant(self):
        """Review P1: KeyboardInterrupt and SystemExit after the issue: revoked, journaled, said so, re-raised."""
        for raised in (KeyboardInterrupt, SystemExit):
            with self.subTest(raised.__name__):
                spy = self.spy()

                def interrupted(*args, **kwargs):
                    raise raised()
                with mock.patch.object(di, 'create_workspace', interrupted), self.assertRaises(raised) as caught:
                    self.run_dispatch(cc.FakeAgentServer(), spy)
                fingerprint = ic.token_fingerprint(spy.issued[0])
                self.assertRevoked(fingerprint)
                attempt = max(self.typed(), key=lambda r: self.store.attempt_identity(r.operation_key).identity.ordinal)
                aid = store_mod.attempt_id_for(attempt.operation_key)
                self.assertEqual(attempt.state, 'reserved')   # the interrupt records no outcome; the revocation does
                self.assertEqual(self.store.get(f'dispatch/attempt/{aid}/inference-revocation/1').state, 'confirmed')
                self.assertIn(fingerprint, '\n'.join(caught.exception.__notes__))
                self.assertCustody(spy.issued[0], fingerprint, caught.exception)
                record = di.end_attempt(self.store, attempt.operation_key, inference=self.access_for(spy),
                                        actor='e-05.6-test')   # the attempt in flight: its recorded revocation
                self.assertTrue(record['revoked'])
                self.assertEqual(len(spy.revoked), 1)
                self.store.transition(attempt.operation_key, 'failed', actor='e-05.6-test', reason='test cleanup')

    def lost(self, spy, *, issued=True, invalid=False):
        """SPY's issue loses its answer: after the broker issued (ISSUED), or before the request reached it."""
        real = spy.issue

        def issue(*args):
            if not issued:
                raise ic.ControlError('CONTROL_UNREACHABLE', '127.0.0.1: synthetic, before sending')
            answer = real(*args)
            if invalid:
                raise ic.ControlError('CONTROL_ANSWER_INVALID', 'synthetic', fingerprint=answer['token_fingerprint'],
                                      conversation_id=answer['conversation_id'], attempt_id=answer['attempt_id'])
            raise ic.ControlError('CONTROL_UNREACHABLE', '127.0.0.1: TimeoutError (synthetic, after sending)')
        spy.issue = issue
        return spy

    def test_a_lost_or_invalid_issue_answer_is_revoked_by_the_attempt(self):
        """Review P3: the broker issued, the answer was lost (or not a valid grant of this attempt): the attempt's
        grant is revoked by its conversation and attempt (and by the fingerprint an invalid answer named)."""
        for name, invalid in (('lost', False), ('invalid', True)):
            with self.subTest(name):
                spy = self.lost(self.spy(), invalid=invalid)
                with self.assertRaises(di.DispatchRefused) as caught:
                    self.run_dispatch(cc.FakeAgentServer(), spy)
                self.assertEqual(caught.exception.code, 'INFERENCE_GRANT_UNAVAILABLE')
                fingerprint = ic.token_fingerprint(spy.issued[-1])
                self.assertRevoked(fingerprint)
                revocation = caught.exception.context['inference_revocation']
                self.assertEqual((revocation['revoked'], revocation['outcome'], revocation['tokenFingerprint']),
                                 (True, 'revoked', fingerprint))
                self.assertEqual(revocation['selectors'], [fingerprint, 'attempt'] if invalid else ['attempt'])
                attempt = max(self.typed(['failed']),
                              key=lambda r: self.store.attempt_identity(r.operation_key).identity.ordinal)
                state, detail = self.journal(store_mod.attempt_id_for(attempt.operation_key))
                self.assertEqual((state, detail['issued'], detail['tokenFingerprint']), ('confirmed', True, fingerprint))
                self.assertCustody(spy.issued[-1], fingerprint, caught.exception)
        self.assertAllRevoked()

    def test_an_answer_lost_before_the_broker_issued_settles_as_no_grant(self):
        spy = self.lost(self.spy(), issued=False)
        with self.assertRaises(di.DispatchRefused) as caught:
            self.run_dispatch(cc.FakeAgentServer(), spy)
        revocation = caught.exception.context['inference_revocation']
        self.assertEqual((revocation['revoked'], revocation['outcome'], revocation['code']),
                         (True, di.NO_GRANT_TOMBSTONED, None))
        key = self.only(['failed']).operation_key
        state, detail = self.journal(store_mod.attempt_id_for(key))
        self.assertEqual((state, detail['issued']), ('failed', False))
        self.assertNoGrant()
        self.assertEqual(di.end_attempt(self.store, key, inference=self.access_for(self.spy()), actor='e-05.6-test'),
                         revocation)

    def test_a_lost_answer_whose_revocation_fails_is_ended_later(self):
        """Review P3 with an unreachable listener: the journal stays unsettled; end_attempt revokes by the attempt
        later and settles the journal and the revocation receipts."""
        spy = self.lost(self.spy(revoke_error=ic.ControlError('CONTROL_UNREACHABLE', 'synthetic')))
        with self.assertRaises(di.DispatchRefused) as caught:
            self.run_dispatch(cc.FakeAgentServer(), spy)
        fingerprint = ic.token_fingerprint(spy.issued[0])
        self.assertEqual(caught.exception.context['inference_revocation']['revoked'], False)
        key = self.only(['failed']).operation_key
        aid = store_mod.attempt_id_for(key)
        self.assertEqual(self.journal(aid)[0], 'dispatched')
        self.assertEqual(self.grant_state(fingerprint)['state'], 'live')
        record = di.end_attempt(self.store, key, inference=self.access_for(self.spy()), actor='e-05.6-test')
        self.assertEqual((record['revoked'], record['selectors'], record['tokenFingerprint']),
                         (True, ['attempt'], fingerprint))
        self.assertRevoked(fingerprint)
        self.assertEqual(self.journal(aid)[:1], ('confirmed',))
        self.assertEqual([self.store.get(f'dispatch/attempt/{aid}/inference-revocation/{n}').state for n in (1, 2)],
                         ['failed', 'confirmed'])

    def test_a_crash_after_the_issue_is_ended_by_the_attempt(self):
        key, fingerprint = self.crashed_after_the_issue()
        record = di.end_attempt(self.store, key, inference=self.access_for(self.spy()), actor='e-05.6-test')
        self.assertEqual((record['revoked'], record['selectors'], record['tokenFingerprint']),
                         (True, ['attempt'], fingerprint))
        self.assertRevoked(fingerprint)
        self.assertEqual(self.journal(store_mod.attempt_id_for(key))[0], 'confirmed')

    def test_an_unsettled_revocation_receipt_is_settled_whatever_its_revoker(self):
        """Review #8: a receipt another revoker left dispatched (interrupted) is resumed and settled."""
        spy = self.spy()
        result = self.run_dispatch(cc.FakeAgentServer(), spy)
        other = di.InferenceAccess(control=self.spy(revoke_error=KeyboardInterrupt()), revoker='another revoker')
        with self.assertRaises(KeyboardInterrupt):
            di.end_attempt(self.store, result.operation_key, inference=other, actor='e-05.6-test')
        receipt = f'dispatch/attempt/{result.attempt_id}/inference-revocation/1'
        self.assertEqual(self.store.get(receipt).state, 'dispatched')
        record = di.end_attempt(self.store, result.operation_key, inference=self.access_for(spy), actor='e-05.6-test')
        self.assertEqual((record['revoked'], record['revoker']), (True, REVOKER))
        self.assertEqual((self.store.get(receipt).state, json.loads(self.store.get(receipt).intent_json)['revoker']),
                         ('confirmed', 'another revoker'))
        self.assertIsNone(self.store.get(f'dispatch/attempt/{result.attempt_id}/inference-revocation/2'))
        self.assertRevoked(ic.token_fingerprint(spy.issued[0]))

    def test_the_broker_revokes_by_conversation_and_attempt(self):
        """The control listener's selector (E-05.6) over the wire: the attempt's one grant; a tombstone when it holds
        none, after which the attempt's issue is GRANT_ATTEMPT_REVOKED; GRANT_UNKNOWN for another conversation's
        grant; GRANT_ALREADY_REVOKED once revoked; a mixed body stays CONTROL_BODY_INVALID."""
        control = self.control()
        conversation, attempt = str(uuid.uuid4()), str(uuid.uuid4())
        answer = control.issue(conversation, attempt, 'anthropic-messages', [d1.TEST_MODEL], 1, 1, 60)
        with self.assertRaises(ic.ControlError) as caught:
            control.revoke_attempt(str(uuid.uuid4()), attempt, 'attempt end', REVOKER)
        self.assertEqual(caught.exception.code, 'GRANT_UNKNOWN')
        other = str(uuid.uuid4())
        tombstone = control.revoke_attempt(conversation, other, 'attempt end', REVOKER)
        self.assertEqual((tombstone['state'], tombstone['attempt_id']), ('tombstoned', other))
        with self.assertRaises(ic.ControlError) as caught:
            control.issue(conversation, other, 'anthropic-messages', [d1.TEST_MODEL], 1, 1, 60)
        self.assertEqual(caught.exception.code, 'GRANT_ATTEMPT_REVOKED')
        revoked = control.revoke_attempt(conversation, attempt, 'attempt end', REVOKER)
        self.assertEqual((revoked['state'], revoked['token_fingerprint']), ('revoked', answer['token_fingerprint']))
        with self.assertRaises(ic.ControlError) as caught:
            control.revoke_attempt(conversation, attempt, 'attempt end', REVOKER)
        self.assertEqual(caught.exception.code, 'GRANT_ALREADY_REVOKED')
        for body in ({'token_fingerprint': answer['token_fingerprint'], 'attempt_id': attempt, 'trigger': 'attempt end',
                      'revoker': REVOKER},
                     {'attempt_id': attempt, 'trigger': 'attempt end', 'revoker': REVOKER}):
            with self.assertRaises(ic.ControlError) as caught:
                control.call('POST', '/v1/grants/revoke', body)
            self.assertEqual(caught.exception.code, 'CONTROL_BODY_INVALID')
        with self.assertRaises(ic.ControlError) as caught:
            control.revoke_attempt('not-a-uuid', attempt, 'attempt end', REVOKER)
        self.assertEqual(caught.exception.code, 'CONVERSATION_ID_INVALID')

    def test_an_issue_held_in_the_broker_past_the_client_s_timeout_never_leaves_a_live_grant(self):
        """Review A (probe P6): the issue request reaches the broker, which is held writing its receipt (a hook in
        the in-process broker) while the client gives up (CONTROL_UNREACHABLE). The dispatcher's revocation by
        attempt then contends for the broker's attempt lock; released, the issue registers its grant, and the
        revocation finds and revokes it. And the other order: a revocation by attempt that finds nothing
        tombstones the attempt, and the late issue is refused (GRANT_ATTEMPT_REVOKED). No live grant either way."""
        for order in ('issue registers first', 'revocation first'):
            with self.subTest(order):
                broker = self.rig().broker
                entered, release = threading.Event(), threading.Event()
                real_record = broker.journal.record
                late = []

                def held_record(key, intent, detail, *, conflict):
                    if intent.get('format') == S.IB.GRANT_FORMAT and order == 'issue registers first':
                        entered.set()
                        release.wait(30)   # held until the revocation contends for the attempt lock
                    return real_record(key, intent, detail, conflict=conflict)
                spy = self.spy()

                def timed_out(*args):
                    spy.events.append('issue')
                    if order == 'issue registers first':
                        worker = threading.Thread(target=lambda: late.append(self.control().issue(*args)))
                        worker.start()
                        self.assertTrue(entered.wait(30))
                        late.append(worker)
                    else:
                        late.append(list(args))   # the request is still on its way; the broker sees it later
                    raise ic.ControlError('CONTROL_UNREACHABLE', '127.0.0.1: TimeoutError (synthetic)')
                spy.issue = timed_out
                with mock.patch.object(broker.journal, 'record', held_record), \
                        mock.patch.object(broker, '_attempt_lock_factory',
                                          lambda: _Contended(threading.Lock(), release.set)):
                    with self.assertRaises(di.DispatchRefused) as caught:
                        self.run_dispatch(cc.FakeAgentServer(), spy)
                    if order == 'issue registers first':
                        late[0].join(30)
                        answer = late[1]
                    else:
                        with self.assertRaises(ic.ControlError) as refused:
                            self.control().issue(*late[0])   # the late issue arrives after the tombstone
                        self.assertEqual(refused.exception.code, 'GRANT_ATTEMPT_REVOKED')
                revocation = caught.exception.context['inference_revocation']
                key = max(self.typed(['failed']),
                          key=lambda r: self.store.attempt_identity(r.operation_key).identity.ordinal).operation_key
                state, detail = self.journal(store_mod.attempt_id_for(key))
                if order == 'issue registers first':
                    self.assertEqual((revocation['outcome'], revocation['tokenFingerprint']),
                                     ('revoked', answer['token_fingerprint']))
                    self.assertRevoked(answer['token_fingerprint'])
                    self.assertEqual((state, detail['issued']), ('confirmed', True))
                else:
                    self.assertEqual((revocation['outcome'], revocation['revoked']), (di.NO_GRANT_TOMBSTONED, True))
                    self.assertEqual((state, detail['issued'], detail['settledBy']),
                                     ('failed', False, di.NO_GRANT_TOMBSTONED))
                    # end_attempt need not call again: the recorded outcome stands
                    calls = self.spy()
                    self.assertEqual(di.end_attempt(self.store, key, inference=self.access_for(calls),
                                                    actor='e-05.6-test'), revocation)
                    self.assertEqual(calls.revoked, [])
                self.assertEqual(self.control().status()['grants']['live'], 0)

    def test_a_wrong_answer_s_fingerprint_of_another_attempt_is_never_revoked(self):
        """Review B (probe P7): an invalid answer names another attempt's grant; it is not revoked or journaled, and
        when the attempt's selector fails the outcome is failed (the attempt's selector decides)."""
        spy = self.spy()
        real = spy.issue
        other = {}

        def invalid(*args):
            real(*args)   # ours is issued
            answer = self.control().issue(str(uuid.uuid4()), str(uuid.uuid4()), 'anthropic-messages',
                                          [d1.TEST_MODEL], 1, 1, 600)
            other.update(answer)
            raise ic.ControlError('CONTROL_ANSWER_INVALID', 'synthetic', fingerprint=answer['token_fingerprint'],
                                  conversation_id=answer['conversation_id'], attempt_id=answer['attempt_id'])

        def unreachable(*args):
            spy.revoked.append(args)
            raise ic.ControlError('CONTROL_UNREACHABLE', 'synthetic')
        spy.issue, spy.revoke_attempt = invalid, unreachable
        with self.assertRaises(di.DispatchRefused) as caught:
            self.run_dispatch(cc.FakeAgentServer(), spy)
        revocation = caught.exception.context['inference_revocation']
        self.assertEqual((revocation['revoked'], revocation['outcome'], revocation['selectors']),
                         (False, 'failed', ['attempt']))
        self.assertEqual(self.grant_state(other['token_fingerprint'])['state'], 'live')   # never another's
        self.assertNotIn(other['token_fingerprint'], self.store.canonical_dump().decode('utf-8'))
        ours = ic.token_fingerprint(spy.issued[0])
        self.assertEqual(self.grant_state(ours)['state'], 'live')
        key = self.only(['failed']).operation_key
        record = di.end_attempt(self.store, key, inference=self.access_for(self.spy()), actor='e-05.6-test')
        self.assertEqual((record['revoked'], record['tokenFingerprint']), (True, ours))
        self.assertRevoked(ours)
        self.assertEqual(self.grant_state(other['token_fingerprint'])['state'], 'live')

    def test_an_attempt_ended_in_flight_sends_no_create(self):
        """Review C (probe P8): end_attempt runs while the dispatch is in flight (before the workspace): the send
        refuses GRANT_REVOKED before any transport call, and the revocation stands."""
        spy = self.spy()
        real = di.create_workspace
        seen = {}

        def ending_first(admitted, **kwargs):
            seen['end'] = di.end_attempt(self.store, admitted.operation_key, inference=self.access_for(self.spy()),
                                         actor='e-05.6-test')
            return real(admitted, **kwargs)
        server = cc.FakeAgentServer()
        with mock.patch.object(di, 'create_workspace', ending_first), self.assertRaises(di.DispatchRefused) as caught:
            self.run_dispatch(server, spy)
        self.assertEqual((caught.exception.code, server.calls), ('GRANT_REVOKED', []))
        fingerprint = ic.token_fingerprint(spy.issued[0])
        self.assertTrue(seen['end']['revoked'])
        self.assertRevoked(fingerprint)
        self.assertEqual(self.only(['failed']).state, 'failed')
        self.assertTrue(caught.exception.context['inference_revocation']['revoked'])


class _Contended:
    """The broker's attempt lock, observed: ON_CONTENDED runs when an acquirer finds it held (then it waits)."""

    def __init__(self, lock, on_contended):
        self.lock, self.on_contended = lock, on_contended

    def __enter__(self):
        if not self.lock.acquire(blocking=False):
            self.on_contended()
            self.lock.acquire()
        return self

    def __exit__(self, *exc):
        self.lock.release()


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

    def test_a_token_value_in_the_admitted_body_is_never_sent(self):
        """Review R5 (probe P4): the admitted body's token secret must be the slot; a token there, even the held
        grant's own, is SECRET_NOT_FROM_GRANT at the send, and no record of that create carries it."""
        _, resolved, admitted = self.reserved_d1()
        token = admitted.inference.token()
        literal = self.wire(self.body_for(resolved, d1.TEST_TEMPLATE), admitted)
        tampered = dataclasses.replace(admitted, body_json=di._canonical(literal))
        refusal = self.assertDenied('SECRET_NOT_FROM_GRANT', self.send, tampered, resolved)
        for text in self.texts_of(refusal, tampered.to_json()):
            self.assertNotIn(token, text)
            self.assertNotIn(token[9:], text)
        self.send(admitted, resolved)
        self.assertEqual(len(self.transport.calls), 1)

    def test_a_split_token_is_withheld_whole(self):
        """Review R6 (probe P5a): a refusal text that, without its characters outside the token's alphabet, holds a
        part of the token of 8 or more characters is replaced whole, detail and context field alike."""
        _, resolved, admitted = self.reserved_d1()
        token = admitted.inference.token()
        body_of = token[9:]
        for separator in ('.', ' ', '/', '+'):
            with self.subTest(separator=separator):
                split = 'aieh-inf-' + separator.join(body_of[i:i + 7] for i in range(0, len(body_of), 7))
                body = self.body_for(resolved, d1.TEST_TEMPLATE)
                body[split] = 'x'
                refusal = self.assertDenied('BODY_FIELD_UNKNOWN', self.send, self.tampered(admitted, body), resolved)
                self.assertEqual((refusal.detail, refusal.context['field']), (di.SCRUBBED_DETAIL, di.SCRUBBED_DETAIL))
                for text in self.texts_of(refusal):
                    self.assertNotIn(body_of, _OUTSIDE.sub('', text))
        # A text without a part of the token keeps its detail.
        body = self.body_for(resolved, d1.TEST_TEMPLATE)
        body['unknown_field'] = 'x'
        refusal = self.assertDenied('BODY_FIELD_UNKNOWN', self.send, self.tampered(admitted, body), resolved)
        self.assertIn('unknown_field', refusal.detail)

    def test_a_scrubbed_refusal_holds_no_chain_to_the_original(self):
        """Review R7 (probe P5b): the scrubbed refusal has no __context__ or __cause__; the custody search walks
        both chains (texts_of)."""
        _, resolved, admitted = self.reserved_d1()
        token = admitted.inference.token()
        body = self.body_for(resolved, d1.TEST_TEMPLATE)
        body[token] = 'x'
        refusal = self.assertDenied('BODY_FIELD_UNKNOWN', self.send, self.tampered(admitted, body), resolved)
        self.assertIsNone(refusal.__context__)
        self.assertIsNone(refusal.__cause__)
        for text in self.texts_of(refusal):
            self.assertNotIn(token, text)
        # Negative control: the search walks a chain, and would see the token there.
        try:
            try:
                raise di.DispatchRefused('BODY_FIELD_UNKNOWN', token)
            except di.DispatchRefused:
                raise di.DispatchRefused('BODY_FIELD_UNKNOWN', 'clean')
        except di.DispatchRefused as chained:
            self.assertTrue(any(token in text for text in self.texts_of(chained)))

    def test_the_revoker_takes_the_broker_s_grammar(self):
        """Review R8: InferenceAccess checks its revoker at construction (INFERENCE_REVOKER_INVALID)."""
        for revoker in ('', 'x' * 201, 'a\nb', 5, None):
            with self.subTest(revoker=revoker):
                with self.assertRaises(di.DispatchRefused) as caught:
                    di.InferenceAccess(control=self.control(), revoker=revoker)
                self.assertEqual(caught.exception.code, 'INFERENCE_REVOKER_INVALID')
        self.assertEqual(di.InferenceAccess(control=self.control(), revoker='x' * 200).revoker, 'x' * 200)


_OUTSIDE = di._OUTSIDE_TOKEN_ALPHABET


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


class RevocationReceipts(SecretsFixture):
    """The dispatcher's revocation receipts (dispatch/attempt/<id>/inference-revocation/<n>) change no attempt's
    outcome as the store's consumers compute it: restore-epoch reconciliation, the epoch's closure and the
    ordinal claims see the same attempts, with or without them. A receipt carries no workRef or outcomeRef (the
    lineage reader skips such reservations), and the owner recorders read their own key prefixes only."""

    def copy_store(self, name):
        path = self.case / name / 'integration.sqlite'
        path.parent.mkdir()
        target = sqlite3.connect(path)
        try:
            self.store.conn.backup(target)
        finally:
            target.close()
        return path

    def restored(self, path):
        """The store at PATH after a backup and its restore: a restore epoch is open."""
        held = store_mod.open_store(path)
        manifest = held.backup(actor='owner')
        held.close()
        store_mod.restore_store(path, path.parent / 'backups' / (manifest['backup_file'] + '.manifest.json'),
                                actor='owner')
        restored = store_mod.open_store(path)
        self.addCleanup(restored.close)
        self.assertTrue(restored.open_epochs())
        return restored

    def reconciled(self, path, key, identity, verdict='not_performed'):
        store, asked = self.restored(path), []

        def oracle(reservation):
            asked.append(reservation.operation_key)
            return verdict
        report = store.reconcile(oracle, actor='reconciler')
        closed = store.close_restore_epoch(actor='owner')
        claims = [(c.operation_key, c.live) for c in store.claims(identity.work_id, identity.design_revision,
                                                                  identity.stage)]
        return {'report': report, 'asked': asked, 'closed': bool(closed), 'state': store.get(key).state,
                'claims': claims, 'unsettled': [a.operation_key for a in store.attempts(['dispatched', 'unknown'])]}

    def test_receipts_change_no_attempt_s_reconciliation(self):
        spy = self.spy()
        result = self.run_dispatch(cc.FakeAgentServer(), spy)
        key = result.operation_key
        identity = self.store.attempt_identity(key).identity
        before = self.copy_store('before')
        failing = self.access_for(self.spy(revoke_error=ic.ControlError('CONTROL_UNREACHABLE', 'synthetic')))
        with self.assertRaises(di.DispatchRefused):
            di.end_attempt(self.store, key, inference=failing, actor='e-05.6-test')   # receipt 1: failed
        interrupting = self.access_for(self.spy(revoke_error=KeyboardInterrupt()))
        with self.assertRaises(KeyboardInterrupt):
            di.end_attempt(self.store, key, inference=interrupting, actor='e-05.6-test')   # receipt 2: dispatched
        interrupted = self.copy_store('interrupted')
        record = di.end_attempt(self.store, key, inference=self.access_for(spy), actor='e-05.6-test')  # resumed
        self.assertTrue(record['revoked'])
        receipts = [f'dispatch/attempt/{result.attempt_id}/inference-revocation/{n}' for n in (1, 2)]
        self.assertEqual([self.store.get(k).state for k in receipts], ['failed', 'confirmed'])
        self.assertEqual(self.store.get(f'dispatch/attempt/{result.attempt_id}/inference-revocation/3'), None)
        after = self.copy_store('after')
        for receipt in receipts:
            intent = json.loads(self.store.get(receipt).intent_json)
            self.assertFalse({'workRef', 'outcomeRef', di.INTENT_KEY} & set(intent))
        # With a confirmed and a failed receipt, the attempt reconciles as it did without them.
        without, with_receipts = self.reconciled(before, key, identity), self.reconciled(after, key, identity)
        self.assertEqual(without, with_receipts)
        self.assertEqual(without['report'], {'confirmed': [], 'failed': [], 'still_unknown': []})
        self.assertEqual((without['asked'], without['state'], without['closed'], without['unsettled']),
                         ([], 'confirmed', True, []))
        # A receipt left dispatched (its revocation's outcome unknown) is reconciled as itself: the oracle is asked
        # about that receipt, never the attempt, whose state is unchanged; once settled the epoch closes.
        grant_journal = f'dispatch/attempt/{result.attempt_id}/inference-grant'
        self.assertEqual(self.store.get(grant_journal).state, 'confirmed')
        self.assertFalse({'workRef', 'outcomeRef', di.INTENT_KEY} & set(json.loads(
            self.store.get(grant_journal).intent_json)))
        uncertain = self.reconciled(interrupted, key, identity)
        self.assertEqual(uncertain['asked'], [receipts[1]])
        self.assertEqual(uncertain['report'], {'confirmed': [], 'failed': [receipts[1]], 'still_unknown': []})
        self.assertEqual((uncertain['state'], uncertain['closed'], uncertain['claims']),
                         ('confirmed', True, without['claims']))

    def test_grant_journals_change_no_attempt_s_reconciliation(self):
        """The grant journal (review R2): a settled one is not seen by reconciliation; one left dispatched by a
        crash after the issue is reconciled as itself (the oracle is asked about the journal, never the attempt,
        which stays reserved: a reserved attempt may stay across an epoch), and end_attempt then still revokes the
        grant by its attempt."""
        key, fingerprint = self.crashed_after_the_issue()
        identity = self.store.attempt_identity(key).identity
        aid = store_mod.attempt_id_for(key)
        crashed = self.reconciled(self.copy_store('crashed'), key, identity)
        self.assertEqual(crashed['asked'], [f'dispatch/attempt/{aid}/inference-grant'])
        self.assertEqual((crashed['state'], crashed['closed'], crashed['unsettled']), ('reserved', True, []))
        di.end_attempt(self.store, key, inference=self.access_for(self.spy()), actor='e-05.6-test')
        self.assertRevoked(fingerprint)
        ended = self.reconciled(self.copy_store('ended'), key, identity)
        self.assertEqual((ended['report'], ended['asked'], ended['state'], ended['claims']),
                         ({'confirmed': [], 'failed': [], 'still_unknown': []}, [], 'reserved', crashed['claims']))


if __name__ == '__main__':
    unittest.main()
