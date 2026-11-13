"""The broker's decisions without a socket (decision 0015 sections 3 and 5 as amended): issuance and its
refusals, family binding, revocation and expiry with their integration-store receipts, budgets, and every
admission refusal, on a Broker whose listeners are never started (connect is a spy that must not be reached).
"""
from __future__ import annotations

import io
import json
import shutil
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

import broker_support as S

CATEGORY = 'unit'
IB = S.IB


SHARED: dict = {}


def setUpModule():
    SHARED['dir'] = Path(tempfile.mkdtemp(prefix='aieh-inference-grants-'))
    SHARED['db'] = SHARED['dir'] / 'integration.sqlite'


def tearDownModule():
    shutil.rmtree(SHARED['dir'], ignore_errors=True)


def never(*args, **kwargs):
    raise AssertionError('admission reached the upstream connector')


class Fixture(unittest.TestCase):
    raw = None

    @classmethod
    def setUpClass(cls):
        raw = cls.raw if cls.raw is not None else S.component(
            {family: 'http://127.0.0.1:9' for family in S.FAMILIES})
        cls.rig = S.Rig(raw, connect=never, db=SHARED['db'])
        cls.broker = cls.rig.broker

    @classmethod
    def tearDownClass(cls):
        cls.rig.close()

    def issue(self, **kwargs):
        return self.rig.issue(**kwargs)

    def code(self, call, *args) -> str:
        with self.assertRaises(IB.InferenceError) as caught:
            call(*args)
        return caught.exception.code

    def admit(self, grant, *, family='openai-chat', model=S.MODEL_A, body=None, target=None, extra=(),
              method='POST', raw=None, token=None):
        token = grant['token'] if token is None else token
        data = raw if raw is not None else json.dumps(body if body is not None else {'model': model,
                                                                                     'input': S.PROMPT_MARKER})\
            .encode()
        pairs = [S.auth(family, token), ('Content-Type', 'application/json')] + list(extra)
        if not any(name.lower() in ('content-length', 'transfer-encoding') for name, _ in extra):
            pairs.append(('Content-Length', str(len(data))))
        return self.broker.admit(method, target or S.ROUTE[family], S.headers(*pairs), io.BytesIO(data).read)

    def refused(self, grant, **kwargs) -> str:
        with self.assertRaises(IB.InferenceError) as caught:
            self.admit(grant, **kwargs)
        return caught.exception.code


class TestIssue(Fixture):
    def test_a_grant_is_journaled_by_fingerprint_and_the_token_is_kept_only_hashed(self):
        grant = self.issue(family='anthropic-messages', models=(S.MODEL_A, S.MODEL_B), requests=3, tokens=50, ttl=60)
        token = grant['token']
        self.assertRegex(token, r'^aieh-inf-[A-Za-z0-9_-]{43}$')
        self.assertEqual(grant['token_fingerprint'], IB.contract.fingerprint(token))
        self.assertEqual((grant['family'], grant['models'], grant['budget'], grant['state']),
                         ('anthropic-messages', [S.MODEL_A, S.MODEL_B], {'requests': 3, 'tokens': 50}, 'live'))
        self.assertEqual(grant['grant_receipt']['events'], ['reserved', 'dispatched', 'confirmed'])
        record, events = self.rig.store_records(f'inference/attempt/{grant["attempt_id"]}/grant')
        intent = json.loads(record.intent_json)
        self.assertEqual(intent['format'], 'aieh-inference-grant/1')
        self.assertEqual(intent['token_fingerprint'], grant['token_fingerprint'])
        self.assertEqual(intent['upstream'], 'http://127.0.0.1:9')
        self.assertNotIn(token, record.intent_json + ''.join(e.detail_json or '' for e in events))
        held = self.broker._by_fingerprint[grant['token_fingerprint']]
        self.assertNotIn(token, json.dumps(vars(held), default=str))
        self.assertEqual(held.digest, IB.digest(token))
        self.assertEqual(self.broker.grant_status(grant['token_fingerprint'])['state'], 'live')

    def test_each_issue_refusal(self):
        base = {'conversation_id': S.new_id(), 'attempt_id': S.new_id(), 'family': 'openai-chat',
                'models': [S.MODEL_A], 'budget': {'requests': 1, 'tokens': 1}, 'ttl_s': 1}

        def variant(**changes):
            body = {**base, 'attempt_id': S.new_id(), **changes}
            return {k: v for k, v in body.items() if v is not ...}
        cases = [
            ('CONTROL_BODY_INVALID', ['not', 'a', 'mapping']),
            ('CONTROL_BODY_INVALID', 5),
            ('CONTROL_BODY_INVALID', None),
            ('BUDGET_INVALID', variant(budget=5)),
            ('MODELS_INVALID', variant(models='syn')),
            ('CONTROL_BODY_INVALID', variant(ttl_s=...)),
            ('CONTROL_BODY_INVALID', variant(note='x')),
            ('CONVERSATION_ID_INVALID', variant(conversation_id='not-a-uuid')),
            ('CONVERSATION_ID_INVALID', variant(conversation_id=S.new_id().upper())),
            ('CONVERSATION_ID_INVALID', variant(conversation_id=5)),
            ('ATTEMPT_ID_INVALID', variant(attempt_id=S.new_id().replace('-', ''))),
            ('FAMILY_UNKNOWN', variant(family='gemini')),
            ('FAMILY_UNKNOWN', variant(family=['openai-chat'])),
            ('MODELS_INVALID', variant(models=[])),
            ('MODELS_INVALID', variant(models=[S.MODEL_A, S.MODEL_A])),
            ('MODELS_INVALID', variant(models=['syn-*'])),
            ('MODELS_INVALID', variant(models=S.MODEL_A)),
            ('MODEL_NOT_ALLOWLISTED', variant(models=[S.MODEL_A, S.MODEL_C])),
            ('BUDGET_INVALID', variant(budget={'requests': 0, 'tokens': 1})),
            ('BUDGET_INVALID', variant(budget={'requests': True, 'tokens': 1})),
            ('BUDGET_INVALID', variant(budget={'requests': 1})),
            ('BUDGET_INVALID', variant(budget={'requests': 1, 'tokens': 1, 'cost': 1})),
            ('BUDGET_INVALID', variant(budget={'requests': 1, 'tokens': 10 ** 11})),
            ('BUDGET_INVALID', variant(budget=[1, 1])),
            ('TTL_INVALID', variant(ttl_s=0)),
            ('TTL_INVALID', variant(ttl_s=86401)),
            ('TTL_INVALID', variant(ttl_s=1.5)),
        ]
        before = len(self.broker._grants)
        for expected, body in cases:
            with self.subTest(expected=expected, body=body):
                self.assertEqual(self.code(self.broker.issue, body), expected)
        self.assertEqual(len(self.broker._grants), before)

    def test_one_grant_per_attempt(self):
        grant = self.issue()
        self.assertEqual(self.code(lambda: self.issue(attempt_id=grant['attempt_id'])), 'ATTEMPT_HAS_GRANT')


class TestReadiness(unittest.TestCase):
    def test_with_the_shipped_empty_allowlists_every_issue_is_refused(self):
        upstreams = {family: 'http://127.0.0.1:9' for family in S.FAMILIES}
        rig = S.Rig(S.component(upstreams, models=()), connect=never, db=SHARED['db'])
        try:
            for family in S.FAMILIES:
                with self.subTest(family=family):
                    with self.assertRaises(IB.InferenceError) as caught:
                        rig.issue(family=family, models=(S.MODEL_A,))
                    self.assertEqual(caught.exception.code, 'MODEL_NOT_ALLOWLISTED')
            self.assertEqual(rig.broker.status()['grants'], {'live': 0, 'revoked': 0, 'receipts_pending': 0})
        finally:
            rig.close()

    def test_a_family_is_not_ready_without_an_upstream_or_its_provider_key(self):
        raw = S.component({'openai-chat': 'http://127.0.0.1:9'}, provider=S.OTHER_PROVIDER)
        raw['families']['anthropic-messages'] = {'provider': S.PROVIDER, 'models': [S.MODEL_A]}
        raw['families']['openai-responses'] = {'upstream': 'http://127.0.0.1:9', 'models': [S.MODEL_A]}
        for key, expected in (((S.PROVIDER, S.KEY), {'anthropic-messages': 'FAMILY_NOT_READY',
                                                     'openai-chat': 'FAMILY_NOT_READY', 'openai-responses': None}),
                              (None, {'openai-chat': 'FAMILY_NOT_READY', 'openai-responses': None})):
            rig = S.Rig(raw, provider_key=key, connect=never, db=SHARED['db'])
            try:
                for family, code in expected.items():
                    with self.subTest(key=key is not None, family=family):
                        try:
                            rig.issue(family=family)
                            got = None
                        except IB.InferenceError as exc:
                            got = exc.code
                        self.assertEqual(got, code)
                status = {f['id']: f['ready'] for f in rig.broker.status()['families']}
                self.assertFalse(status['anthropic-messages'])
                self.assertTrue(status['openai-responses'])  # a keyless loopback upstream (decision 0015 s2.4)
            finally:
                rig.close()


class TestRevocationAndExpiry(Fixture):
    def test_revocation_is_immediate_and_leaves_a_receipt_with_the_summary(self):
        grant = self.issue()
        self.admit(grant)
        self.assertEqual(self.refused(grant, model=S.MODEL_B), 'MODEL_NOT_ALLOWED')
        answer = self.broker.revoke({'token_fingerprint': grant['token_fingerprint'], 'trigger': 'attempt end',
                                     'revoker': 'dispatcher (test)'})
        self.assertEqual(answer['state'], 'revoked')
        self.assertEqual(self.refused(grant), 'TOKEN_REVOKED')
        record, events = self.rig.store_records(f'inference/attempt/{grant["attempt_id"]}/revocation')
        intent = json.loads(record.intent_json)
        self.assertEqual({k: intent[k] for k in ('format', 'token_fingerprint', 'attempt_id', 'conversation_id',
                                                 'trigger', 'revoker')},
                         {'format': 'aieh-inference-revocation/1', 'token_fingerprint': grant['token_fingerprint'],
                          'attempt_id': grant['attempt_id'], 'conversation_id': grant['conversation_id'],
                          'trigger': 'attempt end', 'revoker': 'dispatcher (test)'})
        self.assertEqual((intent['summary']['requests'], intent['summary']['refused'],
                          intent['summary']['in_flight']), (1, 1, 1))
        self.assertEqual([e.to_state for e in events], ['reserved', 'dispatched', 'confirmed'])
        self.assertEqual(self.code(self.broker.revoke, {'token_fingerprint': grant['token_fingerprint'],
                                                        'trigger': 'attempt end', 'revoker': 'x'}),
                         'GRANT_ALREADY_REVOKED')

    def test_each_revoke_refusal(self):
        grant = self.issue()
        fingerprint = grant['token_fingerprint']
        for expected, body in (
                ('CONTROL_BODY_INVALID', {'token_fingerprint': fingerprint, 'trigger': 'attempt end'}),
                ('TRIGGER_UNKNOWN', {'token_fingerprint': fingerprint, 'trigger': 'done', 'revoker': 'x'}),
                ('REVOKER_INVALID', {'token_fingerprint': fingerprint, 'trigger': 'attempt end', 'revoker': ''}),
                ('REVOKER_INVALID', {'token_fingerprint': fingerprint, 'trigger': 'attempt end', 'revoker': 'x' * 201}),
                ('REVOKER_INVALID', {'token_fingerprint': fingerprint, 'trigger': 'attempt end', 'revoker': 'a\nb'}),
                ('REVOKER_INVALID', {'token_fingerprint': fingerprint, 'trigger': 'attempt end', 'revoker': 5}),
                ('GRANT_UNKNOWN', {'token_fingerprint': 'sha256:0000000000000000', 'trigger': 'attempt end',
                                   'revoker': 'x'}),
                ('GRANT_UNKNOWN', {'token_fingerprint': ['x'], 'trigger': 'attempt end', 'revoker': 'x'})):
            with self.subTest(expected=expected, body=body):
                self.assertEqual(self.code(self.broker.revoke, body), expected)
        self.assertEqual(self.code(self.broker.grant_status, 'sha256:0000000000000000'), 'GRANT_UNKNOWN')
        for trigger in IB.TRIGGERS:
            with self.subTest(trigger=trigger):
                other = self.issue()
                self.broker.revoke({'token_fingerprint': other['token_fingerprint'], 'trigger': trigger,
                                    'revoker': 'owner (test)'})

    def test_an_expired_token_answers_401_and_is_revoked_with_trigger_expiry(self):
        grant = self.issue(ttl=30)
        self.admit(grant)
        self.rig.clock.now += 30
        try:
            self.assertEqual(self.refused(grant), 'TOKEN_EXPIRED')
            self.assertEqual(self.refused(grant), 'TOKEN_EXPIRED')
            status = self.broker.grant_status(grant['token_fingerprint'])
            self.assertEqual((status['state'], status['revocation']['trigger'], status['revocation']['revoker']),
                             ('revoked', 'expiry', 'inference-broker (expiry)'))
            self.assertEqual(status['receipt']['state'], 'confirmed')
        finally:
            self.rig.clock.now -= 30

    def test_expiry_is_refused_before_the_body_is_judged(self):
        grant = self.issue(ttl=7)
        self.rig.clock.now += 7
        try:
            self.assertEqual(self.refused(grant, raw=b'not json'), 'TOKEN_EXPIRED')
        finally:
            self.rig.clock.now -= 7

    def test_housekeeping_revokes_unused_expired_grants(self):
        grant = self.issue(ttl=5)
        self.rig.clock.now += 5
        try:
            self.broker.status()
        finally:
            self.rig.clock.now -= 5
        record, _ = self.rig.store_records(f'inference/attempt/{grant["attempt_id"]}/revocation')
        self.assertEqual(json.loads(record.intent_json)['trigger'], 'expiry')
        self.assertEqual(self.refused(grant), 'TOKEN_EXPIRED')


class FlakyStore:
    """A real fixture store whose writes fail while .failing is set."""

    def __init__(self, store, switch):
        self.store, self.switch = store, switch

    def __getattr__(self, name):
        if name in ('reserve', 'transition') and self.switch['failing']:
            raise sqlite3.OperationalError('disk I/O error (synthetic)')
        return getattr(self.store, name)


class TestJournalFailure(unittest.TestCase):
    def setUp(self):
        self.switch = {'failing': False}
        self.rig = S.Rig(S.component({'openai-chat': 'http://127.0.0.1:9'}), connect=never, db=SHARED['db'],
                         store_factory=lambda: FlakyStore(S.STORE.open_store(self.rig.db), self.switch))

    def tearDown(self):
        self.rig.close()

    def test_an_unjournaled_grant_is_never_live(self):
        self.switch['failing'] = True
        with self.assertRaises(IB.InferenceError) as caught:
            self.rig.issue()
        self.assertEqual((caught.exception.code, caught.exception.refusal), ('JOURNAL_FAILED', False))
        self.assertIn('OperationalError', caught.exception.detail)
        self.assertEqual(self.rig.broker.status()['grants']['live'], 0)

    def test_a_revocation_holds_although_its_receipt_waits_and_is_written_later(self):
        grant = self.rig.issue()
        self.switch['failing'] = True
        with self.assertRaises(IB.InferenceError) as caught:
            self.rig.broker.revoke({'token_fingerprint': grant['token_fingerprint'], 'trigger': 'suspected exposure',
                                    'revoker': 'owner (test)'})
        self.assertEqual(caught.exception.code, 'JOURNAL_FAILED')
        with self.assertRaises(IB.InferenceError) as caught:
            self.rig.broker.admit('POST', '/v1/chat/completions', S.headers(S.auth('openai-chat', grant['token'])),
                                  io.BytesIO().read)
        self.assertEqual(caught.exception.code, 'TOKEN_REVOKED')
        self.assertEqual(self.rig.broker.status()['grants']['receipts_pending'], 1)
        self.switch['failing'] = False
        self.assertEqual(self.rig.broker.status()['grants']['receipts_pending'], 0)
        record, _ = self.rig.store_records(f'inference/attempt/{grant["attempt_id"]}/revocation')
        self.assertEqual(json.loads(record.intent_json)['trigger'], 'suspected exposure')

    def test_a_receipt_that_does_not_read_back_as_written_fails(self):
        class Tampering(FlakyStore):
            def get(self, key):
                record = self.store.get(key)
                return None if record is None else IB.dataclasses.replace(record, intent_json='{"format": "x"}')
        rig = S.Rig(S.component({'openai-chat': 'http://127.0.0.1:9'}), connect=never,
                    store_factory=lambda: Tampering(S.STORE.open_store(rig.db), {'failing': False}))
        try:
            with self.assertRaises(IB.InferenceError) as caught:
                rig.issue()
            self.assertEqual(caught.exception.code, 'JOURNAL_FAILED')
            self.assertEqual(rig.broker.status()['grants']['live'], 0)
        finally:
            rig.close()

    def test_a_receipt_that_would_hold_a_secret_is_not_written(self):
        grant = self.rig.issue()
        with self.assertRaises(IB.InferenceError) as caught:
            self.rig.broker.revoke({'token_fingerprint': grant['token_fingerprint'], 'trigger': 'owner direction',
                                    'revoker': f'owner {S.KEY}'})
        self.assertEqual(caught.exception.code, 'EXPOSURE_FOUND')
        self.assertEqual(self.rig.broker.grant_status(grant['token_fingerprint'])['state'], 'revoked')
        store = S.STORE.open_store(self.rig.db)
        try:
            self.assertIsNone(store.get(f'inference/attempt/{grant["attempt_id"]}/revocation'))
            self.assertNotIn(S.KEY, store.canonical_dump().decode('utf-8', 'replace'))
        finally:
            store.close()

    def test_closing_the_journal_closes_its_store(self):
        self.rig.issue()
        self.assertIsNotNone(self.rig.journal._store)
        self.rig.journal.close()
        self.assertIsNone(self.rig.journal._store)
        self.rig.journal = IB.Journal(lambda: S.STORE.open_store(self.rig.db), self.rig.guard)  # for tearDown

    def test_a_broker_without_ports_does_not_start(self):
        rig = S.Rig({'families': {}}, connect=never, db=SHARED['db'])
        try:
            with self.assertRaises(IB.InferenceError) as caught:
                rig.broker.start()
            self.assertEqual(caught.exception.code, 'CONFIG_INCOMPLETE')
            self.assertEqual(rig.broker.listeners, {})
        finally:
            rig.close()

    def test_a_grant_survives_no_restart_but_its_attempt_cannot_be_granted_again(self):
        grant = self.rig.issue()
        again = S.Rig(S.component({'openai-chat': 'http://127.0.0.1:9'}), connect=never,
                      store_factory=lambda: S.STORE.open_store(self.rig.db))
        try:
            with self.assertRaises(IB.InferenceError) as caught:
                again.issue(attempt_id=grant['attempt_id'])
            self.assertEqual(caught.exception.code, 'ATTEMPT_HAS_GRANT')
            with self.assertRaises(IB.InferenceError) as caught:
                again.broker.admit('POST', '/v1/chat/completions',
                                   S.headers(S.auth('openai-chat', grant['token'])), io.BytesIO().read)
            self.assertEqual(caught.exception.code, 'TOKEN_UNKNOWN')
        finally:
            again.close()


class TestAdmission(Fixture):
    def test_an_admitted_request_is_counted_and_forwards_no_credential(self):
        grant = self.issue(models=(S.MODEL_A,))
        admission = self.admit(grant, extra=[('X-Api-Key', grant['token']), ('Cookie', 'c=1'),
                                             ('Connection', 'keep-alive, X-Hop'), ('X-Hop', '1'),
                                             ('X-Forwarded-For', '10.0.0.1'), ('Proxy-Authorization', 'Basic x'),
                                             ('Accept-Encoding', 'gzip'), ('OpenAI-Beta', 'synthetic'),
                                             ('Expect', '100-continue')])
        self.assertEqual((admission.model, admission.path, admission.family.id), (S.MODEL_A, '/v1/chat/completions',
                                                                                 'openai-chat'))
        self.assertEqual(sorted(name.lower() for name, _ in admission.headers), ['content-type', 'openai-beta'])
        held = self.broker._by_fingerprint[grant['token_fingerprint']]
        self.assertEqual((held.requests, held.in_flight, held.refused), (1, 1, 0))

    def test_the_token_is_found_only_in_an_auth_header(self):
        grant = self.issue()
        token = grant['token']
        self.assertEqual(self.code(self.broker.admit, 'POST', '/v1/chat/completions', S.headers(), io.BytesIO().read),
                         'TOKEN_MISSING')
        for pairs, expected in (
                ([('Authorization', f'Basic {token}')], 'TOKEN_MISSING'),
                ([('Authorization', 'Bearer ')], 'TOKEN_MISSING'),
                ([('Authorization', f'Bearer {token}'), ('x-api-key', token + 'x')], 'TOKEN_AMBIGUOUS'),
                ([('Authorization', f'Bearer {token}'), ('Authorization', 'Bearer other')], 'TOKEN_AMBIGUOUS'),
                ([('Authorization', 'Bearer aieh-inf-' + 'A' * 43)], 'TOKEN_UNKNOWN'),
                ([('Authorization', 'Bearer ' + token[:-1])], 'TOKEN_UNKNOWN'),
                ([('x-api-key', token)], 'TOKEN_WRONG_HEADER')):
            with self.subTest(pairs=[name for name, _ in pairs], expected=expected):
                self.assertEqual(self.code(self.broker.admit, 'POST', '/v1/chat/completions', S.headers(*pairs),
                                           io.BytesIO().read), expected)
        self.assertEqual(self.admit(grant, extra=[('x-api-key', token)]).model, S.MODEL_A)  # the same token twice
        anthropic = self.issue(family='anthropic-messages')
        self.assertEqual(self.refused(anthropic, family='openai-chat', target='/v1/messages'), 'TOKEN_WRONG_HEADER')

    def test_the_route_is_the_family_set_exactly(self):
        grant = self.issue(family='anthropic-messages')
        for method, target in (('POST', '/v1/chat/completions'), ('POST', '/v1/responses'), ('GET', '/v1/messages'),
                               ('POST', '/v1/messages/'), ('POST', '/v1/messages/count_tokens'),
                               ('POST', '/v1/%6dessages'), ('POST', 'http://evil.example/v1/messages'),
                               ('CONNECT', 'evil.example:443'), ('POST', '//v1/messages'), ('POST', '/V1/messages')):
            with self.subTest(method=method, target=target):
                self.assertEqual(self.refused(grant, family='anthropic-messages', method=method, target=target),
                                 'ROUTE_NOT_ALLOWED')
        self.assertEqual(self.refused(grant, family='anthropic-messages', target='/v1/messages?beta=true'),
                         'QUERY_NOT_ALLOWED')
        self.assertEqual(self.broker._by_fingerprint[grant['token_fingerprint']].refused, 11)

    def test_the_body_and_its_model(self):
        grant = self.issue(models=(S.MODEL_A,))
        for kwargs, expected in (
                ({'extra': [('Transfer-Encoding', 'chunked')]}, 'BODY_LENGTH_REQUIRED'),
                ({'extra': [('Transfer-Encoding', 'chunked'), ('Content-Length', '28')]}, 'BODY_LENGTH_REQUIRED'),
                ({'extra': [('Content-Length', '5'), ('Content-Length', '5')]}, 'BODY_LENGTH_INVALID'),
                ({'extra': [('Content-Length', '-1')]}, 'BODY_LENGTH_INVALID'),
                ({'extra': [('Content-Length', '99')]}, 'BODY_LENGTH_INVALID'),
                ({'extra': [('Content-Length', str(32 * 1024 * 1024 + 1))]}, 'BODY_TOO_LARGE'),
                ({'raw': b'not json'}, 'BODY_NOT_JSON'),
                ({'raw': b'\xff\xfe'}, 'BODY_NOT_JSON'),
                ({'raw': b''}, 'BODY_NOT_JSON'),
                ({'body': [S.MODEL_A]}, 'BODY_NOT_JSON'),
                ({'body': {'input': 'x'}}, 'MODEL_MISSING'),
                ({'body': {'model': ''}}, 'MODEL_MISSING'),
                ({'body': {'model': [S.MODEL_A]}}, 'MODEL_MISSING'),
                ({'model': S.MODEL_B}, 'MODEL_NOT_ALLOWED'),
                ({'model': S.MODEL_C}, 'MODEL_NOT_ALLOWED'),
                ({'body': {'model': S.MODEL_A, 'input': grant['token']}}, 'TOKEN_IN_REQUEST'),
                ({'extra': [('X-Trace', 'id ' + grant['token'])]}, 'TOKEN_IN_REQUEST')):
            with self.subTest(kwargs=kwargs, expected=expected):
                self.assertEqual(self.refused(grant, **kwargs), expected)
        self.assertEqual(self.broker._by_fingerprint[grant['token_fingerprint']].requests, 0)
        no_length = S.headers(S.auth('openai-chat', grant['token']))
        self.assertEqual(self.code(self.broker.admit, 'POST', '/v1/chat/completions', no_length, io.BytesIO().read),
                         'BODY_LENGTH_REQUIRED')

    def test_request_and_token_budgets(self):
        grant = self.issue(requests=2, tokens=100)
        held = self.broker._by_fingerprint[grant['token_fingerprint']]
        self.admit(grant)
        self.admit(grant)
        self.assertEqual(self.refused(grant), 'BUDGET_REQUESTS_EXHAUSTED')
        tokens = self.issue(requests=100, tokens=100)
        spent = self.broker._by_fingerprint[tokens['token_fingerprint']]
        self.admit(tokens)
        spent.total_tokens = 100
        self.assertEqual(self.refused(tokens), 'BUDGET_TOKENS_EXHAUSTED')
        unknown = self.issue(requests=100, tokens=100)
        self.broker._by_fingerprint[unknown['token_fingerprint']].unknown_usage = 1
        self.assertEqual(self.refused(unknown), 'BUDGET_USAGE_UNKNOWN')
        self.assertEqual((held.requests, held.refused), (2, 1))


class TestQueryPassFamily(Fixture):
    """A declaration may admit a query (query: pass); the token may then not travel in it."""

    @classmethod
    def setUpClass(cls):
        declarations = IB.load_declarations()
        declarations['openai-chat'] = IB.dataclasses.replace(declarations['openai-chat'], query='pass')
        cls.rig = S.Rig(S.component({'openai-chat': 'http://127.0.0.1:9'}), connect=never, db=SHARED['db'])
        cls.rig.broker.config = IB.load_config(S.component({'openai-chat': 'http://127.0.0.1:9'}), declarations,
                                               allow_ephemeral=True)
        cls.broker = cls.rig.broker

    def test_a_passed_query_never_carries_the_token(self):
        grant = self.issue()
        self.assertEqual(self.admit(grant, target='/v1/chat/completions?api-version=1').path, '/v1/chat/completions')
        self.assertEqual(self.refused(grant, target='/v1/chat/completions?key=' + grant['token']), 'TOKEN_IN_REQUEST')

    def test_an_upstream_or_key_lost_after_issue_refuses_before_any_connection(self):
        grant = self.issue()
        config = self.broker.config
        try:
            families = dict(config.families)
            families['openai-chat'] = IB.dataclasses.replace(families['openai-chat'], upstream=None)
            self.broker.config = IB.dataclasses.replace(config, families=families)
            self.assertEqual(self.refused(grant), 'UPSTREAM_NOT_CONFIGURED')
            self.broker.config = config
            key, self.broker.provider_key = self.broker.provider_key, None
            try:
                self.assertEqual(self.refused(grant), 'PROVIDER_KEY_ABSENT')
            finally:
                self.broker.provider_key = key
        finally:
            self.broker.config = config


class FakeHandler:
    """What _send_refusal and _drain use of a request handler, in memory."""

    def __init__(self, guard, body=b'', **headers):
        self.headers = S.headers(*((name.replace('_', '-'), value) for name, value in headers.items()))
        self.rfile, self.wfile, self.lines = io.BytesIO(body), io.BytesIO(), []
        self.server = type('Server', (), {'broker': type('Broker', (), {'guard': guard})})
        self.close_connection = False

    def send_response_only(self, status, message=None):
        self.lines.append(('status', status))

    def send_header(self, name, value):
        self.lines.append((name, value))

    def end_headers(self):
        pass


class TestRefusalResponses(unittest.TestCase):
    def test_a_small_unread_body_is_drained_and_a_large_or_chunked_one_is_not(self):
        guard = IB.BrokerGuard()
        for headers, body, read in (({'content_length': '5'}, b'hello', 5),
                                    ({'content_length': str(IB.DRAIN_LIMIT + 1)}, b'x' * 10, 0),
                                    ({'content_length': '5', 'transfer_encoding': 'chunked'}, b'hello', 0),
                                    ({}, b'hello', 0)):
            with self.subTest(headers=headers):
                handler = FakeHandler(guard, body, **headers)
                IB._send_refusal(handler, IB.InferenceError('TOKEN_MISSING', 'x'))
                self.assertEqual(handler.rfile.tell(), read)
                self.assertTrue(handler.close_connection)
                self.assertIn(('Connection', 'close'), handler.lines)
        handler = FakeHandler(guard, b'hello', content_length='5')
        handler.body_consumed = True
        IB._send_refusal(handler, IB.InferenceError('TOKEN_MISSING', 'x'))
        self.assertEqual(handler.rfile.tell(), 0)

    def test_a_refusal_that_would_hold_a_secret_is_withheld(self):
        guard = IB.BrokerGuard()
        guard.hold(S.KEY)
        handler = FakeHandler(guard)
        IB._send_refusal(handler, IB.InferenceError('TOKEN_UNKNOWN', f'saw {S.KEY}'))
        answer = handler.wfile.getvalue()
        self.assertNotIn(S.KEY.encode(), answer)
        self.assertEqual(json.loads(answer)['aieh_refusal']['code'], 'EXPOSURE_FOUND')
        self.assertIn(('status', 401), handler.lines)


class FakeResponse:
    def __init__(self, chunks, *, length):
        self.status, self.reason, self.length, self.chunks = 200, 'OK', length, list(chunks)

    def getheader(self, name):
        return 'application/json' if name == 'content-type' else None

    def getheaders(self):
        return [('Content-Type', 'application/json')]

    def read1(self, size):
        return self.chunks.pop(0) if self.chunks else b''


class FakeConnection:
    def __init__(self, response):
        self.response, self.sent = response, []

    def putrequest(self, method, target, **kwargs):
        self.sent.append((method, target))

    def putheader(self, name, value):
        self.sent.append((name, value))

    def endheaders(self, body=None):
        self.sent.append(body)

    def getresponse(self):
        return self.response

    def close(self):
        pass


class TestSettledBeforeTheLastByte(Fixture):
    """The grant's accounting and the audit line are written before the answer's last bytes leave, so the
    client's next request (or a status read) already meets them: for an answer with a length and a chunked one."""

    def test_both_answer_shapes(self):
        answer = json.dumps(S.json_answer('openai-chat')).encode()
        for length in (len(answer), None):
            with self.subTest(length=length):
                grant = self.issue()
                held = self.broker._by_fingerprint[grant['token_fingerprint']]
                connection = FakeConnection(FakeResponse([answer[:10], answer[10:]], length=length))
                self.broker._connect = lambda origin, timeout: connection
                body = json.dumps({'model': S.MODEL_A}).encode()
                handler = FakeHandler(self.rig.guard, body, content_length=str(len(body)),
                                      authorization=f'Bearer {grant["token"]}')
                handler.command, handler.path = 'POST', '/v1/chat/completions'
                seen = []

                class Watch(io.BytesIO):
                    def write(inner, data):
                        seen.append((bytes(data), held.in_flight, held.total_tokens, self.rig.audit.lines))
                        return super().write(data)
                handler.wfile = Watch()
                lines = self.rig.audit.lines
                self.broker.serve_inference(handler)
                self.assertEqual(seen[0][1:], (1, 0, lines))          # the first bytes: still in flight
                self.assertEqual(seen[-1][1:], (0, 18, lines + 1))    # the last bytes: settled and audited
                self.assertEqual(connection.sent[0], ('POST', '/v1/chat/completions'))
                self.assertIn(('authorization', f'Bearer {S.KEY}'), connection.sent)
        self.broker._connect = never


class GateLock:
    """The broker's attempt lock, observed: ON_CONTENDED runs when an acquirer finds it held (then it waits)."""

    def __init__(self, on_contended):
        self.lock, self.on_contended = threading.Lock(), on_contended

    def __enter__(self):
        if not self.lock.acquire(blocking=False):
            self.on_contended()
            self.lock.acquire()
        return self

    def __exit__(self, *exc):
        self.lock.release()


class TestRevocationByAttempt(unittest.TestCase):
    """E-05.6: a revocation by conversation and attempt that finds no grant tombstones the attempt, under the same
    lock and the same store key as an issue's registration: whichever comes first, no grant of the attempt is
    live after it."""
    REVOKE = {'trigger': 'attempt end', 'revoker': 'dispatcher (test)'}

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix='aieh-inference-tombstone-'))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.db = self.dir / 'integration.sqlite'
        self.rig = self.new_rig()

    def new_rig(self):
        rig = S.Rig(S.component({'openai-chat': 'http://127.0.0.1:9'}), connect=never, db=self.db)
        self.addCleanup(rig.close)
        return rig

    def body(self, conversation, attempt):
        return {'conversation_id': conversation, 'attempt_id': attempt, 'family': 'openai-chat',
                'models': [S.MODEL_A], 'budget': {'requests': 1, 'tokens': 1}, 'ttl_s': 60}

    def code(self, call, *args) -> str:
        with self.assertRaises(IB.InferenceError) as caught:
            call(*args)
        return caught.exception.code

    def test_a_revocation_first_tombstones_the_attempt_and_refuses_its_issue(self):
        conversation, attempt = S.new_id(), S.new_id()
        answer = self.rig.broker.revoke({'conversation_id': conversation, 'attempt_id': attempt, **self.REVOKE})
        self.assertEqual((answer['format'], answer['state'], answer['attempt_id']),
                         (IB.TOMBSTONE_FORMAT, 'tombstoned', attempt))
        again = self.rig.broker.revoke({'conversation_id': conversation, 'attempt_id': attempt, **self.REVOKE})
        self.assertEqual(again['state'], 'tombstoned')   # idempotent: the same tombstone
        self.assertEqual(self.code(self.rig.broker.issue, self.body(conversation, attempt)), 'GRANT_ATTEMPT_REVOKED')
        self.assertEqual(self.rig.broker.status()['grants']['live'], 0)
        # durable: a broker restarted on the same store refuses it too
        restarted = self.new_rig()
        self.assertEqual(self.code(restarted.broker.issue, self.body(conversation, attempt)), 'GRANT_ATTEMPT_REVOKED')
        self.assertEqual(restarted.broker.status()['grants']['live'], 0)
        # the attempt's receipt key holds the tombstone, never a token
        held, _ = self.rig.store_records(f'inference/attempt/{attempt}/grant')
        self.assertEqual(json.loads(held.intent_json)['format'], IB.TOMBSTONE_FORMAT)

    def test_an_issue_in_flight_is_registered_and_then_revoked(self):
        """The issue holds the attempt lock (its receipt is being written) when the revocation by attempt arrives:
        the revocation waits, then finds the registered grant and revokes it."""
        conversation, attempt = S.new_id(), S.new_id()
        broker = self.rig.broker
        entered, release, contended = threading.Event(), threading.Event(), threading.Event()
        real_record = broker.journal.record

        def held_record(key, intent, detail, *, conflict):
            if intent.get('format') == IB.GRANT_FORMAT:
                entered.set()
                self.assertTrue(release.wait(30), 'the revocation never contended for the attempt lock')
            return real_record(key, intent, detail, conflict=conflict)

        def on_contended():
            contended.set()
            release.set()   # the revocation is waiting on the lock: let the issue finish
        broker.journal.record = held_record
        broker._attempt_lock = GateLock(on_contended)
        issued = []
        worker = threading.Thread(target=lambda: issued.append(broker.issue(self.body(conversation, attempt))))
        worker.start()
        self.assertTrue(entered.wait(30))
        answer = broker.revoke({'conversation_id': conversation, 'attempt_id': attempt, **self.REVOKE})
        worker.join(30)
        self.assertTrue(contended.is_set())
        self.assertEqual((answer['state'], answer['token_fingerprint']), ('revoked', issued[0]['token_fingerprint']))
        self.assertEqual(broker.grant_status(issued[0]['token_fingerprint'])['state'], 'revoked')
        self.assertEqual(broker.status()['grants']['live'], 0)

    def test_a_revocation_while_an_issue_waits_tombstones_and_the_issue_is_refused(self):
        """The revocation holds the attempt lock first (its tombstone is being written) when the issue arrives: the
        issue waits, then is refused."""
        conversation, attempt = S.new_id(), S.new_id()
        broker = self.rig.broker
        entered, release = threading.Event(), threading.Event()
        real_record = broker.journal.record

        def held_record(key, intent, detail, *, conflict):
            if intent.get('format') == IB.TOMBSTONE_FORMAT:
                entered.set()
                self.assertTrue(release.wait(30), 'the issue never contended for the attempt lock')
            return real_record(key, intent, detail, conflict=conflict)
        broker.journal.record = held_record
        broker._attempt_lock = GateLock(release.set)
        answers = []
        worker = threading.Thread(target=lambda: answers.append(broker.revoke(
            {'conversation_id': conversation, 'attempt_id': attempt, **self.REVOKE})))
        worker.start()
        self.assertTrue(entered.wait(30))
        self.assertEqual(self.code(broker.issue, self.body(conversation, attempt)), 'GRANT_ATTEMPT_REVOKED')
        worker.join(30)
        self.assertEqual(answers[0]['state'], 'tombstoned')
        self.assertEqual(broker.status()['grants']['live'], 0)

    def test_a_grant_of_another_conversation_or_an_earlier_run_is_grant_unknown(self):
        conversation, attempt = S.new_id(), S.new_id()
        grant = self.rig.broker.issue(self.body(conversation, attempt))
        self.assertEqual(self.code(self.rig.broker.revoke, {'conversation_id': S.new_id(), 'attempt_id': attempt,
                                                            **self.REVOKE}), 'GRANT_UNKNOWN')
        self.assertEqual(self.rig.broker.grant_status(grant['token_fingerprint'])['state'], 'live')
        restarted = self.new_rig()   # the grant ended with the earlier run; its receipt stays
        self.assertEqual(self.code(restarted.broker.revoke, {'conversation_id': conversation, 'attempt_id': attempt,
                                                             **self.REVOKE}), 'GRANT_UNKNOWN')
        self.assertEqual(self.code(restarted.broker.issue, self.body(conversation, attempt)), 'ATTEMPT_HAS_GRANT')


class TestEveryCodeIsExercised(unittest.TestCase):
    def test_each_stable_code_appears_in_a_test(self):
        text = ''.join(path.read_text(encoding='utf-8') for path in S.HERE.glob('test_*.py'))
        missing = [code for code in IB.CODES if f"'{code}'" not in text]
        self.assertEqual(missing, [])


if __name__ == '__main__':
    unittest.main()
