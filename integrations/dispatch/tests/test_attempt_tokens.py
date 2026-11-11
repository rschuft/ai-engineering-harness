"""Tests for the per-attempt role-token delivery (plan leaf E-01.3.3), offline.

Run from the repository root:

    python -I -B -m unittest discover -s integrations/dispatch/tests -v

The proof, on the E-01.3.1 fixture (a fake Agent Server replaying the pinned 1.60.1 answers), with an
in-memory credential provider standing in for Windows Credential Manager and a fake Gitea answering
``GET /api/v1/token`` as Gitea 28.3.0 does (its own login and scopes):

* each stage uses exactly its mapped bot: the provider is asked for that one entry only, and Gitea is asked
  about that one token;
* a missing or mismatched credential (no entry, an entry naming another account, a value that is not a
  token, another bot's token, other scopes, a revoked token, a lost or malformed answer, a failing provider)
  refuses, and no token is delivered;
* only a confirmed attempt gets a token, and nothing is read for any other;
* no Agent Server call carries a delivered token or its fingerprint (the create of another attempt sent while
  one is held, and calls that try to carry it, which are refused before the transport);
* records and refusals carry the fingerprint only.

Every value is synthetic. No guest, Gitea, Agent Server, credential store or network is used.
"""
from pathlib import Path
import ast
import copy
import hashlib
import http.client
import importlib.util
import json
import pickle
import sys
import unittest
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


cc = _load('test_conversation_create', HERE / 'test_conversation_create.py')
adm, base, di, store_mod = cc.adm, cc.base, cc.di, cc.store_mod
at = _load('attempt_tokens', HERE.parent / 'attempt_tokens.py')
roles = at.roles
PORT = 13300


def synthetic(label):
    return hashlib.sha1(f'synthetic role token {label}'.encode()).hexdigest()


TOKENS = {role: synthetic(role) for role in ('planner', 'builder', 'reviewer', 'verifier')}


def shown_tokens(text):
    """The roles whose token (in any case) TEXT holds."""
    return [role for role, token in TOKENS.items() if token in text.lower()]


class MemoryProvider(roles.host.CredentialProvider):
    """Credential Manager, in memory: entries by name; every read recorded."""

    def __init__(self, entries, error=None):
        self.entries, self.reads, self.error = dict(entries), [], error

    def get(self, name):
        self.reads.append(name)
        if self.error is not None:
            raise self.error
        return self.entries.get(name)

    def set(self, name, user, secret, comment=''):
        raise AssertionError('the delivery never writes an entry')

    def delete(self, name):
        raise AssertionError('the delivery never deletes an entry')


class FakeGitea:
    """``GET /api/v1/token`` of Gitea 28.3.0, with gitea_host.http_get's signature: 200 and the token's
    view (its name, scopes and user) for a known token, 401 for any other; ``fault`` answers instead."""

    def __init__(self, tokens, fault=None):
        self.tokens, self.fault, self.requests = dict(tokens), fault, []

    def __call__(self, port, path, *, method='GET', body=None, headers=None, timeout=None):
        auth = (headers or {}).get('Authorization', '')
        self.requests.append((port, method, path, auth))
        if isinstance(self.fault, BaseException):
            raise self.fault
        if self.fault is not None:
            return self.fault
        if (method, path) != ('GET', '/api/v1/token'):
            raise AssertionError(f'the delivery sends GET /api/v1/token only, not {method} {path}')
        view = self.tokens.get(auth.removeprefix('token '))
        if view is None:
            return 401, {}, b'{"message":"invalid username, password or token"}'
        return 200, {}, json.dumps({'id': 7, 'name': view['name'], 'scopes': view['scopes'],
                                    'user': {'id': 9, 'login': view['login']}}).encode()


def entries():
    return {roles.target(role): (roles.ROLES[role]['user'], token) for role, token in TOKENS.items()}


def views():
    return {token: {'login': roles.ROLES[role]['user'], 'scopes': list(roles.ROLES[role]['scopes']),
                    'name': f'aieh-{role}-20261111T000000Z'} for role, token in TOKENS.items()}


class StageMappingTests(unittest.TestCase):
    """The mapping against the store's stages and the role-token matrix."""
    category = 'contract'

    def test_each_stage_maps_to_its_own_dispatcher_delivered_bot(self):
        self.assertEqual(at.STAGE_ROLES, {'implement': 'builder', 'review': 'reviewer'})
        self.assertEqual(set(at.STAGE_ROLES), set(store_mod.STAGES))
        matrix = json.loads((REPO / 'policy' / 'role-tokens.json').read_text(encoding='utf-8'))
        rows = {row['id']: row for row in matrix['roles']}
        custodian = set(rows['management-dispatcher']['custodian_of'])
        for stage, role in at.STAGE_ROLES.items():
            credential = roles.ROLES[role]['credential']
            with self.subTest(stage=stage, role=role):
                self.assertIn(credential, custodian)
                issuance = [i for i in rows[role]['issuance'] if i['credential'] == credential]
                self.assertEqual([i['delivered_by'] for i in issuance], ['management-dispatcher'])
                self.assertIn(credential, rows[role]['grants']['credentials'])
                self.assertTrue(rows[role]['agent_controlled'])
                others = {roles.ROLES[r]['credential'] for r in at.STAGE_ROLES.values() if r != role}
                self.assertTrue(others <= set(rows[role]['denied']), others)

    def test_the_module_refuses_an_incomplete_mapping(self):
        """STAGE_ROLES must cover exactly the store's stages, each with a role gitea_roles knows."""
        source = (HERE.parent / 'attempt_tokens.py').read_text(encoding='utf-8')
        for name, patch in (('a stage without a role', mock.patch.object(di, 'STAGES', (*di.STAGES, 'deploy'))),
                            ('a role gitea_roles lacks', mock.patch.dict(roles.ROLES, clear=False))):
            with self.subTest(name), patch:
                if name == 'a role gitea_roles lacks':
                    del roles.ROLES['reviewer']
                with self.assertRaisesRegex(ImportError, 'STAGE_ROLES'):
                    exec(compile(source, 'attempt_tokens.py', 'exec'), {'__file__': str(HERE.parent / 'attempt_tokens.py'),
                                                                        '__name__': 'attempt_tokens_check'})
        self.assertIn('reviewer', roles.ROLES)

    def test_holds_are_counted_and_released(self):
        token = synthetic('held')
        digest, fp = hashlib.sha256(token.encode()).hexdigest(), roles.fingerprint(token)
        self.addCleanup(di._HELD_ROLE_TOKENS.pop, digest, None)
        self.assertFalse(di._carries_held_role_token('/p', {'x': token}))
        di.hold_role_token(digest, fp)
        di.hold_role_token(digest, fp)
        di.release_role_token(digest)
        for body in ({'x': token}, {'x': f'a {token}'}, {'x': 'Bearer' + token}, {'x': 'cafe' + token + 'beef'},
                     {'x': fp}, {'x': fp.partition(':')[2]}, [[token]]):
            self.assertTrue(di._carries_held_role_token('/p', body), body)
        self.assertTrue(di._carries_held_role_token('/p/' + token, None))
        self.assertFalse(di._carries_held_role_token('/p', {'x': token.upper()[:39]}))
        self.assertFalse(di._carries_held_role_token('/p', {'x': synthetic('other')}))
        di.release_role_token(digest)
        self.assertFalse(di._carries_held_role_token('/p', {'x': token}))
        di.release_role_token(digest)
        self.assertEqual(di._HELD_ROLE_TOKENS, {})


class DeliveryFixture(adm.AdmissionFixture):
    """attempt_role_token on attempts dispatched through the E-01.3.1 fixture (helpers; no tests)."""

    def setUp(self):
        super().setUp()
        self.provider = MemoryProvider(entries())
        self.gitea = FakeGitea(views())
        self.addCleanup(self.assertEqual, di._HELD_ROLE_TOKENS, {}, 'a role token is still held')

    def confirmed(self, stage='implement', server=None):
        """The key of a confirmed attempt of STAGE (implement on demo-app, review on other-app)."""
        manifest, request, sources = None, self.request(), self.sources
        if stage == 'review':
            data = self.manifest_data()
            data['designs'].append({'repository': 'other-app', 'change': base.CHANGE, 'commit': self.commit})
            manifest = self.write_manifest(data, self.fresh('manifest'))
            request = self.request(repository='other-app', stage='review', catalog_pin='reviewer-pin')
            sources = {'other-app': self.sources['demo-app']}
        manifest = manifest or self.write_manifest(self.manifest_data(), self.fresh('manifest'))
        result = di.dispatch(request, manifest=manifest, work_sources=sources.get, integration_store=self.store,
                             workspaces=self.workspaces, transport=server or cc.FakeAgentServer(),
                             actor='token-test', read_profile=self.read_profile, read_artifact=self.read_artifact)
        return result.operation_key

    def deliver(self, key, provider=None, gitea=None):
        return at.attempt_role_token(self.store, key, provider=provider or self.provider, port=PORT,
                                     http=gitea or self.gitea)

    def refused(self, code, key, provider=None, gitea=None, reads=None, requests=None):
        provider, gitea = provider or self.provider, gitea or self.gitea
        with self.assertRaises(di.DispatchRefused) as caught:
            with self.deliver(key, provider, gitea):
                self.fail('a refused delivery must not enter the attempt context')
        self.assertEqual(caught.exception.code, code, caught.exception.detail)
        text = json.dumps(caught.exception.to_json()) + str(caught.exception)
        self.assertEqual(shown_tokens(text), [], 'a refusal carries no token')
        if reads is not None:
            self.assertEqual(provider.reads, reads)
        if requests is not None:
            self.assertEqual(len(gitea.requests), requests)
        return caught.exception

    def check_delivery(self, stage, role):
        key = self.confirmed(stage)
        token, bot = TOKENS[role], roles.ROLES[role]['user']
        with self.deliver(key) as delivery:
            self.assertEqual(self.provider.reads, [roles.target(role)], 'exactly the mapped entry is read')
            self.assertEqual(self.gitea.requests, [(PORT, 'GET', '/api/v1/token', 'token ' + token)])
            credential = delivery.credential()
            self.assertEqual((credential.username, credential.scheme, credential.authorization()),
                             (bot, 'token', 'token ' + token))
            record = delivery.record()
            self.assertEqual(record, {
                'format': at.DELIVERY_FORMAT, 'operationKey': key, 'attemptId': store_mod.attempt_id_for(key),
                'stage': stage, 'role': role, 'bot': bot, 'entry': f'AIEH Gitea bot {role}',
                'credential': f'cred-gitea-bot-{role}', 'scopes': ['write:repository'],
                'fingerprint': roles.fingerprint(token)})
            for shown in (json.dumps(record), repr(delivery), str(delivery), repr(credential)):
                self.assertEqual(shown_tokens(shown), [], shown)
            self.assertIn(f"fingerprint='{roles.fingerprint(token)}', open=True", repr(delivery))
            for serialize in (pickle.dumps, copy.deepcopy, copy.copy):
                with self.assertRaisesRegex(TypeError, 'not serializable'):
                    serialize(delivery)
        self.assertFalse(delivery.open)
        self.assertIn('open=False', repr(delivery))
        with self.assertRaisesRegex(ValueError, 'the attempt context has ended'):
            delivery.credential()
        self.assertNotIn(token, self.store.canonical_dump().decode('utf-8'))
        return key



class DeliveryTests(DeliveryFixture):
    """attempt_role_token on attempts dispatched through the E-01.3.1 fixture."""

    # -- each stage uses exactly its mapped bot --------------------------------

    def test_implement_delivers_the_builder_token_and_nothing_else(self):
        self.check_delivery('implement', 'builder')

    def test_review_delivers_the_reviewer_token_and_nothing_else(self):
        self.check_delivery('review', 'reviewer')

    # -- never inside a container --------------------------------------------

    def test_no_agent_server_call_carries_a_delivered_token(self):
        """While the builder token is held, another attempt's create carries neither the token nor its
        fingerprint, and any call that would is refused before the transport."""
        key = self.confirmed('implement')
        token, fp = TOKENS['builder'], roles.fingerprint(TOKENS['builder'])
        server = cc.FakeAgentServer()
        with self.deliver(key):
            review_key = self.confirmed('review', server)
            self.assertEqual(self.store.get(review_key).state, 'confirmed')
            sent = json.dumps(server.calls)
            for needle in (token, fp, fp.partition(':')[2]):
                self.assertNotIn(needle, sent)
                self.assertNotIn(needle, self.store.canonical_dump().decode('utf-8'))
            body = copy.deepcopy(adm.TEMPLATE)
            for carried in ({'tags': {'aieh': token}}, {'agent_settings': {'secrets': {'GITEA_TOKEN': token}}},
                            {'tags': {'x': fp}}, {'tags': {'x': 'fp ' + fp.partition(':')[2]}}):
                transport = cc.Recorder({'status': 201, 'body': {}})
                with self.subTest(carried=sorted(carried)), self.assertRaises(di.DispatchRefused) as caught:
                    cc.client(transport).call('POST', '/api/conversations', body={**body, **carried})
                self.assertEqual(caught.exception.code, 'ROLE_TOKEN_EXPOSURE')
                self.assertEqual(transport.calls, [], 'refused before the transport')
        # Once the attempt context has ended the guard holds nothing: the same call reaches the transport.
        transport = cc.Recorder({'status': 201, 'body': {}})
        cc.client(transport).call('POST', '/api/conversations', body={**body, 'tags': {'aieh': token}})
        self.assertEqual(len(transport.calls), 1)

    # -- fail closed on a missing or mismatched credential ---------------------

    def test_missing_entry_is_refused_before_gitea(self):
        key = self.confirmed()
        del self.provider.entries[roles.target('builder')]
        self.refused('ROLE_TOKEN_MISSING', key, reads=['AIEH Gitea bot builder'], requests=0)

    def test_mismatched_entries_are_refused(self):
        key = self.confirmed()
        entry = roles.target('builder')
        cases = {
            'another account': (('aieh-bot-reviewer', TOKENS['builder']), 0),
            'upper case': (('aieh-bot-builder', TOKENS['builder'].upper()), 0),
            'too short': (('aieh-bot-builder', TOKENS['builder'][:39]), 0),
            'too long': (('aieh-bot-builder', TOKENS['builder'] + '0'), 0),
            'with a newline': (('aieh-bot-builder', TOKENS['builder'] + '\n'), 0),
            'not text': (('aieh-bot-builder', TOKENS['builder'].encode()), 0),
            'the reviewer\'s token': (('aieh-bot-builder', TOKENS['reviewer']), 1),
            'the planner\'s token': (('aieh-bot-builder', TOKENS['planner']), 1),
            'the verifier\'s token (other scopes)': (('aieh-bot-builder', TOKENS['verifier']), 1)}
        for name, (value, requests) in cases.items():
            with self.subTest(name):
                provider = MemoryProvider({**entries(), entry: value})
                gitea = FakeGitea(views())
                self.refused('ROLE_TOKEN_MISMATCH', key, provider, gitea, reads=[entry], requests=requests)

    def test_a_token_of_the_bot_with_other_scopes_is_refused(self):
        key = self.confirmed()
        for scopes in (['write:repository', 'write:user'], ['read:repository'], ['all'], []):
            with self.subTest(scopes=scopes):
                changed = views()
                changed[TOKENS['builder']]['scopes'] = scopes
                self.refused('ROLE_TOKEN_MISMATCH', key, gitea=FakeGitea(changed))

    def test_gitea_refusals_and_lost_answers_are_refused(self):
        key = self.confirmed()
        revoked = views()
        del revoked[TOKENS['builder']]
        self.refused('ROLE_TOKEN_REJECTED', key, gitea=FakeGitea(revoked), requests=1)
        faults = {'500': (500, {}, b'{}'), 'not JSON': (200, {}, b'<html>'), 'a list': (200, {}, b'[]'),
                  'no user': (200, {}, b'{"scopes": ["write:repository"]}'),
                  'no scopes': (200, {}, b'{"user": {"login": "aieh-bot-builder"}}'),
                  'lost': ConnectionResetError(), 'refused': ConnectionRefusedError(),
                  'bad status line': http.client.BadStatusLine('')}
        for name, fault in faults.items():
            with self.subTest(name):
                refusal = self.refused('ROLE_TOKEN_UNVERIFIED', key, gitea=FakeGitea(views(), fault=fault), requests=1)
                if name == '500':
                    self.assertEqual(refusal.context, {'status': 500})

    def test_a_failing_provider_is_refused(self):
        key = self.confirmed()
        for error in (OSError('CredReadW'), RuntimeError('locked'), roles.GiteaError('X', 'y')):
            with self.subTest(error=type(error).__name__):
                self.refused('ROLE_TOKEN_UNAVAILABLE', key, provider=MemoryProvider(entries(), error), requests=0)

    def test_the_stored_record_is_checked_before_any_read(self):
        """stored_inputs on a confirmed attempt: a stored digest, intent or identity that is not the
        dispatch record's is RESERVATION_INVALID, and nothing is read."""
        key = self.confirmed()
        real_get = self.store.get
        good = real_get(key)

        def stored(**changes):
            return mock.patch.object(self.store, 'get', lambda k: store_mod.Reservation(
                **{**real_get(k).__dict__, **changes}))

        def digested(text):
            return {'intent_json': text, 'intent_digest': hashlib.sha256(text.encode()).hexdigest()}

        intent = json.loads(good.intent_json)
        intent[di.INTENT_KEY]['ordinal'] = 0  # outside the identity's range, with a consistent digest
        cases = {'another digest': {'intent_digest': '0' * 64},
                 'not strict JSON': digested(good.intent_json[:-1] + ', "x": NaN}'),
                 'an invalid identity': digested(store_mod.canonical_intent(intent))}
        for name, changes in cases.items():
            with self.subTest(name), stored(**changes):
                self.refused('RESERVATION_INVALID', key, reads=[], requests=0)
        with self.assertRaises(ValueError):
            di.stored_inputs(self.store, key, state='failed')

    def test_only_a_confirmed_attempt_gets_a_token(self):
        self.refused('RESERVATION_INVALID', 'attempt/v1/TASK-9/x@y/implement/1', reads=[], requests=0)
        with self.assertRaises(di.DispatchRefused):
            self.confirmed(server=cc.FakeAgentServer(create={'status': 422, 'body': {}}))
        key = self.store.attempts(['failed'])[0].operation_key
        self.refused('ATTEMPT_NOT_CONFIRMED', key, reads=[], requests=0)
        resolved = self.resolve()
        self.store.reserve_attempt(resolved.attempt_identity(), resolved.intent(), actor='token-test')
        self.refused('ATTEMPT_NOT_CONFIRMED', resolved.attempt_identity().operation_key, reads=[], requests=0)


class GuestApiFake:
    """tools/guest.py GuestApi's call shape, answering as the pinned server (GET /server_info, the create); every
    request it is given is kept: what would travel over SSH into the guest."""

    def __init__(self):
        self.requests = []

    def __call__(self, requests, timeout=900, secret=None):
        self.requests.append(copy.deepcopy(requests))
        (request,) = requests
        if (request['method'], request['path']) == cc.INFO:
            answer = cc.SERVER_INFO
        else:
            answer = copy.deepcopy(cc.CREATE_ANSWER)
            answer['body']['id'] = request['json']['conversation_id']
        return {'responses': [{'status': answer['status'], 'body': answer['body']}], 'session_key_occurrences': 0}


class AdministratorProvider(MemoryProvider):
    """The administrative lifecycle's writes (gitea_roles.py rotate) into the same entries the delivery reads."""

    def __init__(self, shared):
        super().__init__({})
        self.entries = shared.entries

    def set(self, name, user, secret, comment=''):
        self.entries[name] = (user, secret)


class AdministratorGitea(FakeGitea):
    """The fake Gitea as the administrative rotate sees it: a token's own view, and a repository read that a refused
    token answers with 401. It never answers DELETE /api/v1/token for a delivery (the base class refuses it)."""

    def __call__(self, port, path, *, method='GET', body=None, headers=None, timeout=None):
        if path.startswith('/api/v1/repos/'):
            self.requests.append((port, method, path, (headers or {}).get('Authorization', '')))
            return 401, {}, b'{}'
        return super().__call__(port, path, method=method, body=body, headers=headers, timeout=timeout)


class MintingCli:
    """Gitea's CLI as the site administrator runs it: mint gives a new token that the fake Gitea then knows."""

    def __init__(self, gitea):
        self.gitea, self.minted = gitea, []

    def mint(self, user, name, scopes):
        token = synthetic(f'minted {len(self.minted)}')
        self.minted.append(token)
        self.gitea.tokens[token] = {'login': user, 'scopes': list(scopes), 'name': name}
        return token


class StandingCredentialTests(DeliveryFixture):
    """The three lifecycles (the Owner's correction of 2026-11-11): the standing bot credential is used per attempt
    and released, never revoked by the dispatcher; an actually revoked one fails closed until the administrative
    lifecycle replaces it; a stage's credential never reaches the guest or another stage's attempt."""

    def assert_only_token_views_asked(self, gitea=None):
        """Nothing revokes: the only request the delivery sent to Gitea is GET /api/v1/token."""
        gitea = gitea or self.gitea
        self.assertEqual({(method, path) for _port, method, path, _auth in gitea.requests},
                         {('GET', '/api/v1/token')})

    def test_two_sequential_attempts_of_a_stage_use_the_standing_credential(self):
        first, second = self.confirmed('implement'), self.confirmed('implement')
        self.assertNotEqual(first, second)
        for key in (first, second):
            with self.deliver(key) as delivery:
                self.assertEqual(delivery.credential().authorization(), 'token ' + TOKENS['builder'])
                self.assertEqual(delivery.record()['operationKey'], key)
            self.assertFalse(delivery.open)
        self.assertEqual(self.provider.reads, [roles.target('builder')] * 2)
        self.assert_only_token_views_asked()
        self.assertIn(TOKENS['builder'], self.gitea.tokens, 'the standing token stays valid')
        self.assertEqual(self.provider.entries[roles.target('builder')], ('aieh-bot-builder', TOKENS['builder']))

    def test_concurrent_attempts_of_a_stage_cannot_invalidate_one_another(self):
        """Two attempts hold the stage's one standing token; the first released (out of order) leaves the second's
        credential usable and the guard holding it; nothing revokes; the last release ends the guard's hold."""
        first, second = self.confirmed('implement'), self.confirmed('implement')
        token = TOKENS['builder']
        one, two = self.deliver(first), self.deliver(second)
        held_one, held_two = one.__enter__(), two.__enter__()
        released = False
        try:
            one.__exit__(None, None, None)
            released = True
            self.assertFalse(held_one.open)
            self.assertTrue(held_two.open)
            self.assertEqual(held_two.credential().authorization(), 'token ' + token)
            with self.assertRaises(di.DispatchRefused) as caught:
                cc.client(cc.Recorder({'status': 201, 'body': {}})).call(
                    'POST', '/api/conversations', body={**adm.TEMPLATE, 'tags': {'aieh': token}})
            self.assertEqual(caught.exception.code, 'ROLE_TOKEN_EXPOSURE', 'still held by the second attempt')
            with self.deliver(self.confirmed('implement')) as third:  # a later attempt joins while one holds
                self.assertEqual(third.credential().authorization(), 'token ' + token)
            self.assertTrue(held_two.open)
        finally:
            if not released:
                one.__exit__(None, None, None)
            two.__exit__(None, None, None)
        self.assertEqual(di._HELD_ROLE_TOKENS, {})
        self.assert_only_token_views_asked()
        self.assertIn(token, self.gitea.tokens)

    def test_a_revoked_credential_fails_closed_until_the_administrative_lifecycle_replaces_it(self):
        key = self.confirmed('implement')
        gitea = AdministratorGitea(views())
        del gitea.tokens[TOKENS['builder']]  # revoked in Gitea (by the administrator, or on another trigger)
        for _ in range(2):
            self.refused('ROLE_TOKEN_REJECTED', key, gitea=gitea)
        self.assertEqual(self.provider.entries[roles.target('builder')][1], TOKENS['builder'], 'nothing replaced it')
        # The administrative lifecycle (gitea_roles.py rotate, the site administrator's act) replaces the entry; it
        # resumes over the token Gitea already refuses (no second revocation) and mints a new one.
        cli = MintingCli(gitea)
        report = roles.rotate('builder', ctx=(None, None, PORT, AdministratorProvider(self.provider), cli),
                              http=gitea, receipts=self.store)
        self.assertEqual((report['old_before']['status'], report['revocation']),
                         (401, 'already refused by Gitea (revoked earlier)'))
        (new,) = cli.minted
        self.assertEqual(self.provider.entries[roles.target('builder')], ('aieh-bot-builder', new))
        with self.deliver(key, gitea=gitea) as delivery:
            self.assertEqual(delivery.credential().authorization(), 'token ' + new)
            self.assertEqual(delivery.fingerprint, roles.fingerprint(new))
        self.assertNotIn(('DELETE', '/api/v1/token'), {(m, p) for _port, m, p, _a in gitea.requests})
        self.assertEqual(shown_tokens(self.store.canonical_dump().decode('utf-8')), [])
        self.assertNotIn(new, self.store.canonical_dump().decode('utf-8'))

    def test_no_stage_credential_reaches_the_guest_through_the_live_transport(self):
        """While the builder token is held: another attempt dispatched over the live transport (GuestTransport on a
        GuestApi) sends neither the token nor its fingerprint into the guest, and a call that would carry it is
        refused before the transport, so GuestApi is never called with it."""
        gt = _load('guest_transport', HERE.parent / 'guest_transport.py')
        profile = json.loads((REPO / 'profiles' / 'strong-windows-qemu-whpx' / 'profile.json').read_text(
            encoding='utf-8'))
        token = TOKENS['builder']
        needles = (token, roles.fingerprint(token), roles.fingerprint(token).partition(':')[2])
        api = GuestApiFake()
        live = gt.GuestTransport(api, profile, api_login='agent')
        with self.deliver(self.confirmed('implement')):
            review_key = self.confirmed('review', live)
            self.assertEqual(self.store.get(review_key).state, 'confirmed')
            self.assertEqual([r[0]['method'] for r in api.requests], ['GET', 'POST'])
            for needle in needles:
                self.assertNotIn(needle, json.dumps(api.requests))
            sent = len(api.requests)
            for carried in ({'tags': {'aieh': token}}, {'tags': {'x': needles[1]}}, {'tags': {'x': needles[2]}}):
                with self.subTest(carried=carried), self.assertRaises(di.DispatchRefused) as caught:
                    cc.client(live).call('POST', '/api/conversations', body={**adm.TEMPLATE, **carried})
                self.assertEqual(caught.exception.code, 'ROLE_TOKEN_EXPOSURE')
            with self.assertRaises(di.DispatchRefused):
                cc.client(live).call('GET', '/api/conversations/{conversation_id}', params={'conversation_id': token})
            self.assertEqual(len(api.requests), sent, 'refused before the live transport')
        for needle in needles:
            self.assertNotIn(needle, json.dumps([api.requests, live.calls]))

    def test_an_attempt_cannot_acquire_another_stages_credential(self):
        """The stage comes from the attempt's own stored record only: attempt_role_token takes no stage, role, bot
        or entry; an implement attempt reads the builder's entry and no other, even when only the reviewer's
        exists; a stored record that is another attempt's (another stage) is RESERVATION_INVALID before any
        read."""
        import inspect
        self.assertEqual(list(inspect.signature(at.attempt_role_token).parameters),
                         ['integration_store', 'operation_key', 'provider', 'port', 'http'])
        implement, review = self.confirmed('implement'), self.confirmed('review')
        only_reviewer = MemoryProvider({roles.target('reviewer'): entries()[roles.target('reviewer')]})
        self.refused('ROLE_TOKEN_MISSING', implement, provider=only_reviewer, reads=[roles.target('builder')],
                     requests=0)
        only_builder = MemoryProvider({roles.target('builder'): entries()[roles.target('builder')]})
        self.refused('ROLE_TOKEN_MISSING', review, provider=only_builder, reads=[roles.target('reviewer')],
                     requests=0)
        stored = self.store.get(review)
        with mock.patch.object(self.store, 'get', lambda k: stored if k == implement else None):
            self.refused('RESERVATION_INVALID', implement, reads=[], requests=0)
        with self.deliver(review) as delivery:
            self.assertEqual((delivery.stage, delivery.role, delivery.bot), ('review', 'reviewer', 'aieh-bot-reviewer'))
            self.assertEqual(delivery.credential().authorization(), 'token ' + TOKENS['reviewer'])


class ReachableNamesTests(unittest.TestCase):
    """What the dispatch package's own code can reach, read from its syntax trees (the credentials README pattern):
    no mint, no CLI, no entry write, no administrative act and no revocation; Gitea is only asked for a token's own
    view (GET /api/v1/token)."""
    category = 'contract'

    @classmethod
    def setUpClass(cls):
        cls.trees = {path.name: ast.parse(path.read_text(encoding='utf-8'))
                     for path in sorted(HERE.parent.glob('*.py'))}

    def names(self, tree):
        return ({n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
                | {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)})

    def test_the_package_never_reaches_the_mint_or_an_administrative_act(self):
        self.assertIn('attempt_tokens.py', self.trees)
        forbidden = {'mint', 'Cli', 'create_bot', 'store_token', 'provision', 'rotate', 'retire', 'revoke_current',
                     'admin_api', 'basic_header', 'FINAL_TARGETS', 'escape_probe', 'apply_fixture', 'delete'}
        for name, tree in self.trees.items():
            with self.subTest(module=name):
                self.assertEqual(sorted(self.names(tree) & forbidden), [])
                constants = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
                self.assertFalse({c for c in constants if 'generate-access-token' in c or 'access_token' in c})

    def test_gitea_is_asked_for_the_tokens_own_view_only(self):
        calls = [n for n in ast.walk(self.trees['attempt_tokens.py'])
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'call']
        self.assertEqual([[a.value for a in c.args] for c in calls], [['GET', '/token']])
        # a provider is only read: no set or delete on it anywhere in the package
        for name, tree in self.trees.items():
            setters = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == 'set'
                       and isinstance(n.value, ast.Name) and n.value.id == 'provider']
            self.assertEqual(setters, [], name)

    def test_the_check_would_see_a_mint(self):
        """Negative control: the same reading finds a mint and a revocation planted in a copy of the module."""
        source = (HERE.parent / 'attempt_tokens.py').read_text(encoding='utf-8')
        planted = ast.parse(source + "\nroles.Cli(None, None).mint('u', 'n', ())\nroles.revoke_current(1, 't')\n")
        self.assertEqual(sorted(self.names(planted) & {'mint', 'Cli', 'revoke_current'}), ['Cli', 'mint', 'revoke_current'])


if __name__ == '__main__':
    unittest.main()
