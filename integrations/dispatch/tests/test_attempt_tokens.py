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
import copy
import hashlib
import http.client
import importlib.util
import json
import sys
import unittest

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


class DeliveryTests(adm.AdmissionFixture):
    """attempt_role_token on attempts dispatched through the E-01.3.1 fixture."""

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
            with self.assertRaises(TypeError):
                copy.deepcopy(delivery)
        self.assertFalse(delivery.open)
        with self.assertRaises(ValueError):
            delivery.credential()
        self.assertNotIn(token, self.store.canonical_dump().decode('utf-8'))
        return key

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
                self.refused('ROLE_TOKEN_UNVERIFIED', key, gitea=FakeGitea(views(), fault=fault), requests=1)

    def test_a_failing_provider_is_refused(self):
        key = self.confirmed()
        for error in (OSError('CredReadW'), RuntimeError('locked'), roles.GiteaError('X', 'y')):
            with self.subTest(error=type(error).__name__):
                self.refused('ROLE_TOKEN_UNAVAILABLE', key, provider=MemoryProvider(entries(), error), requests=0)

    def test_only_a_confirmed_attempt_gets_a_token(self):
        self.refused('RESERVATION_INVALID', 'attempt/v1/TASK-9/x@y/implement/1', reads=[], requests=0)
        with self.assertRaises(di.DispatchRefused):
            self.confirmed(server=cc.FakeAgentServer(create={'status': 422, 'body': {}}))
        key = self.store.attempts(['failed'])[0].operation_key
        self.refused('ATTEMPT_NOT_CONFIRMED', key, reads=[], requests=0)
        resolved = self.resolve()
        self.store.reserve_attempt(resolved.attempt_identity(), resolved.intent(), actor='token-test')
        self.refused('ATTEMPT_NOT_CONFIRMED', resolved.attempt_identity().operation_key, reads=[], requests=0)


if __name__ == '__main__':
    unittest.main()
