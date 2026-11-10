"""The Owner authorization recorder's parts (plan leaf P-04.2), in the test process only.

Run from the repository root, under the tools interpreter:

    <tools python> -I -B -m unittest discover -s integrations/owner/tests -v

The fake Gitea (fake_gitea.FakeGitea) is called in memory here, with gitea_host.http_get's signature: no
socket is opened. These tests cover the shared record's ``authorize-operation`` subject, the trailers and
the merge message, the policy comparison, the session's fixed calls, the credential checks that refuse
before anything is sent, the codes and remedies, that a fixture context never reaches the managed data
root or the platform's credential store, and the command line. Every statement is synthetic.
"""
import contextlib
import datetime
import io
import json
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

CATEGORY = 'unit'

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import authz_support as su  # noqa: E402

AR, D, fg = su.AR, su.D, su.fg
SUBJECT = {'repository': fg.REPOSITORY, 'pull': 3, 'base': 'main', 'head': 'a' * 40,
           'manifest': 'operations/op-0001.json', 'digest': 'sha256:' + 'b' * 64, 'operation': 'op-0001',
           'operationKind': 'example-effect', 'target': 'example-target', 'expiresAt': su.EXPIRES}


def setUpModule():
    su.start()


def tearDownModule():
    su.stop()


def decision(**subject):
    return {'format': D.FORMAT, 'decisionId': '1f0e2d3c-4b5a-4968-8776-0123456789ab', 'kind': AR.KIND,
            'subject': {**SUBJECT, **subject},
            'shown': {'summary': 'shown', 'nonce': 'ab' * 16, 'expiresAt': su.EXPIRES},
            'statement': su.statement(), 'recordedBy': su.RECORDED_BY, 'recordedAt': '2026-11-10T12:05:00Z'}


class InMemory(su.Fixture):
    def gitea_for_test(self):
        gitea = fg.FakeGitea()
        return gitea, 3000, gitea


class Record(unittest.TestCase):
    """The shared Owner decision record's authorize-operation subject (owner_decision.py)."""

    def test_an_authorize_operation_record_has_the_shared_shape(self):
        self.assertEqual(D.check_record(decision()), [])

    def test_each_subject_problem(self):
        cases = {
            'repository': decision(repository='no-slash'),
            'pull': decision(pull=True),
            'pull number': decision(pull=0),
            'base': decision(base='../main'),
            'head': decision(head='HEAD'),
            'operation': decision(operation='Op_1'),
            'manifest': decision(manifest='operations/other.json'),
            'digest': decision(digest='b' * 64),
            'operationKind': decision(operationKind='Kind'),
            'target': decision(target='two\nlines'),
            'expiresAt': decision(expiresAt='tomorrow'),
        }
        for name, record in cases.items():
            with self.subTest(name=name):
                self.assertNotEqual(D.check_record(record), [])
        missing = decision()
        del missing['subject']['target']
        self.assertTrue(any('subject must have exactly' in p for p in D.check_record(missing)))


class Message(unittest.TestCase):
    def test_trailers_round_trip_through_the_message(self):
        record = decision()
        values = AR.trailers(record, SUBJECT['head'], SUBJECT['digest'])
        self.assertEqual(tuple(values), AR.TRAILERS)
        title, body = AR.merge_message(record, values)
        self.assertEqual(AR.parse_trailers(title + '\n\n' + body.strip() + '\n'), values)
        self.assertIn(f'Merged under Owner authority by the recorder on decision {record["decisionId"]}.', body)
        self.assertNotIn('merged by the owner', (title + body).lower())

    def test_parse_trailers_reads_the_last_paragraph_only(self):
        self.assertEqual(AR.parse_trailers('t\n\nAIEH-Recorder: x\n\nbody'), {})
        self.assertEqual(AR.parse_trailers('t\r\n\r\nAIEH-Recorder: x\r\n'), {'AIEH-Recorder': 'x'})
        self.assertEqual(AR.parse_trailers('t\n\nAIEH-Recorder: x\nAIEH-Recorder: y\n'), {'AIEH-Recorder': None})


class PolicyComparison(unittest.TestCase):
    def test_the_fixture_policy_and_its_drift(self):
        policy = AR.admitted_policies()[fg.REPOSITORY]
        self.assertEqual(policy.base, 'main')
        repo = {**policy.repository, 'permissions': {'admin': False, 'push': True, 'pull': True, 'extra': 1}}
        self.assertEqual(AR.policy_drift(policy, repo, dict(policy.branch)), [])
        self.assertEqual(AR.policy_drift(policy, repo, {**policy.branch, 'status_check_contexts': None}), [])
        self.assertNotEqual(AR.policy_drift(policy, repo, {**policy.branch, 'status_check_contexts': ['ci']}), [])
        drift = AR.policy_drift(policy, {**repo, 'allow_merge_commits': False}, {**policy.branch, 'protected': False})
        self.assertEqual([f for f, _, _ in drift], ['repository.allow_merge_commits', 'branch.protected'])
        self.assertIn('block_admin_merge_override', policy.unobservable)
        self.assertTrue(any(f.startswith('enable_bypass_allowlist') for f in policy.unobservable))  # finding F-A

    def test_the_expected_policy_is_the_fixture_s_declared_protection(self):
        rule = next(r for r in AR.roles.protection_rules() if r['rule_name'] == 'main')
        policy = AR.admitted_policies()[f'{AR.roles.FIXTURE_ORG}/{AR.roles.FIXTURE_REPO}']
        self.assertEqual(policy.branch['required_approvals'], rule['required_approvals'])
        self.assertEqual(rule['merge_whitelist_usernames'], [AR.OWNER])
        self.assertIs(rule['enable_push'], False)


class ProtectionSeam(InMemory):
    """The protection verifier's seam (decision 0012 point 6): only a well-formed ProtectionVerdict counts;
    anything else is unverified, and only verified passes."""

    def answer(self, verifier):
        return AR.check_protection(self.context(verifier=verifier), fg.REPOSITORY, 'main', 'before-merge')

    def test_only_a_well_formed_verdict_counts(self):
        malformed = {
            'None': None, 'a dict': {'status': 'verified', 'detail': 'x'}, 'a tuple': ('verified', 'x', None),
            'an unknown status': AR.ProtectionVerdict('ok', 'x'),
            'a status of another case': AR.ProtectionVerdict('Verified', 'x'),
            'a detail that is no text': AR.ProtectionVerdict('verified', None),
            'a short digest': AR.ProtectionVerdict('verified', 'x', 'sha256:abc'),
            'a digest without its algorithm': AR.ProtectionVerdict('verified', 'x', 'c' * 64),
            'a digest that is no text': AR.ProtectionVerdict('verified', 'x', b'sha256:' + b'c' * 64),
        }
        for name, answer in malformed.items():
            with self.subTest(answer=name):
                got = self.answer(lambda *args, answer=answer: answer)
                self.assertEqual((got['verdict'], got['digest']), ('unverified', None))
                self.assertIn('not a well-formed ProtectionVerdict', got['detail'])
                self.assertRaises(AR.RecorderError, AR.require_verified, got)
        for status in AR.PROTECTION_VERDICTS:
            with self.subTest(status=status):
                got = self.answer(lambda *args, status=status: AR.ProtectionVerdict(status, 'd' * 600))
                self.assertEqual((got['verdict'], len(got['detail']), got['digest']), (status, 500, None))
        self.assertEqual(self.answer(None), {'verdict': 'unverified', 'detail': AR.NO_VERIFIER, 'digest': None})

    def test_an_exception_is_unverified_and_its_text_is_not_repeated(self):
        def raising(*args):
            raise RuntimeError('a message that might hold anything')

        got = self.answer(raising)
        self.assertEqual(got, {'verdict': 'unverified', 'detail': 'the protection verifier raised RuntimeError',
                               'digest': None})

    def test_the_verdicts_and_their_codes(self):
        verdict = lambda status: {'verdict': status, 'detail': 'd', 'digest': None}  # noqa: E731
        self.assertIsNone(AR.require_verified(verdict('verified')))
        self.assertIsNone(AR.protection_code(verdict('verified')))
        for status, code in (('drift', 'PROTECTION_DRIFT'), ('unverified', 'PROTECTION_UNVERIFIED'),
                             ('anything else', 'PROTECTION_UNVERIFIED')):
            with self.subTest(status=status):
                self.assertEqual(AR.protection_code(verdict(status)), code)
                self.assertRefused(code, AR.require_verified, verdict(status))

    def test_the_bracket(self):
        one = {'verdict': 'verified', 'detail': 'a', 'digest': 'sha256:' + 'c' * 64}
        self.assertEqual(AR.bracket(one, {**one, 'detail': 'b'}), {'before': one, 'after': {**one, 'detail': 'b'},
                                                                   'equal': True})
        for change in ({'digest': None}, {'verdict': 'drift'}, {'digest': 'sha256:' + 'e' * 64}):
            with self.subTest(change=change):
                got = AR.bracket(one, {**one, **change})
                self.assertEqual((got['equal'], got['code']), (False, 'PROTECTION_CHANGED_AFTER_MERGE'))

    def test_a_verifier_must_be_callable(self):
        number = self.propose()
        with self.assertRaises(ValueError):
            AR.prepare(self.context(verifier='verified'), fg.REPOSITORY, number)
        self.assertEqual(self.gitea.requests, [])


class Session(InMemory):
    def test_the_session_makes_only_its_fixed_calls(self):
        session = AR.open_session(self.ctx)
        for path in ('/admin/users', '/users/aieh-owner/tokens/1', '/repos/a/b/branch_protections',
                     '/user?sudo=aieh-owner', f'/repos/{fg.REPOSITORY}/raw/README.md?ref={"a" * 40}'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                session.get(path)
        with self.assertRaises(ValueError):
            session.merge(f'/repos/{fg.REPOSITORY}/pulls/1/merge', {'Do': 'merge'})
        merging = AR.Gitea(self.ctx, fg.PASSWORD, may_merge=True)
        body = dict(zip(AR.MERGE_BODY_KEYS, ('merge', 't', 'm', 'a' * 40, False)))
        for bad in ({**body, 'force_merge': True}, {**body, 'Do': 'squash'}, {**body, 'delete_branch_after_merge': True},
                    {k: v for k, v in body.items() if k != 'head_commit_id'}):
            with self.subTest(body=bad), self.assertRaises(ValueError):
                merging.merge(f'/repos/{fg.REPOSITORY}/pulls/1/merge', bad)
        with self.assertRaises(ValueError):
            merging.merge('/users/aieh-owner/tokens', body)
        session.close()
        with self.assertRaises(ValueError):
            session.get('/user')
        self.assertEqual({r['method'] for r in self.gitea.requests}, {'GET'})

    def test_the_credential_is_read_by_name_and_held_only_by_the_session(self):
        session = AR.open_session(self.ctx)
        self.assertEqual(self.provider.reads, [AR.OWNER_ENTRY])
        self.assertEqual(AR.OWNER_ENTRY, 'AIEH Gitea owner')
        session.close()
        self.assertIsNone(session._password)


class CredentialInput(InMemory):
    """Every bot token and every foreign entry is refused before anything is sent."""

    def test_refused_inputs_send_nothing(self):
        cases = {'missing': None, 'empty': (fg.OWNER, ''), 'site admin': ('aieh-site-admin', 'x'),
                 **{f'{bot} and its token': (bot, token) for bot, token in fg.BOT_TOKENS.items()},
                 **{f'aieh-owner with the token of {bot}': (fg.OWNER, token) for bot, token in fg.BOT_TOKENS.items()},
                 'aieh-owner with an upper-case token': (fg.OWNER, 'A' * 40)}
        for name, entry in cases.items():
            with self.subTest(entry=name):
                self.provider.entries = {} if entry is None else {AR.OWNER_ENTRY: entry}
                code = 'CREDENTIAL_MISSING' if entry is None else 'CREDENTIAL_REFUSED'
                self.assertRefused(code, AR.open_session, self.ctx)
        self.assertEqual(self.gitea.requests, [])


class Manifest(unittest.TestCase):
    def test_each_invalid_manifest(self):
        cases = {
            'too large': su.manifest(padding='x' * AR.MANIFEST_MAX_BYTES),
            'not UTF-8': b'\xff\xfe',
            'not JSON': b'operation: op-0001\n',
            'a list': b'[]',
            'no target': json.dumps({'operation': 'op-0001', 'kind': 'k', 'expiresAt': su.EXPIRES}).encode(),
            'another operation': su.manifest(operation='op-0002'),
            'kind': su.manifest(kind='Upper'),
            'target on two lines': su.manifest(target='a\nb'),
            'blank target': su.manifest(target='  '),
            'long target': su.manifest(target='t' * 501),
            'expiry': su.manifest(expiresAt='2026-11-11'),
        }
        for name, blob in cases.items():
            with self.subTest(case=name), self.assertRaises(AR.RecorderError) as caught:
                AR.read_manifest(blob, 'op-0001')
            self.assertEqual(caught.exception.code, 'MANIFEST_INVALID')
        self.assertEqual(AR.read_manifest(su.manifest(extra={'typed': 'later'}), 'op-0001')['kind'], 'example-effect')


class Faults(InMemory):
    """What Gitea answers otherwise, read by read, refuses before anything is merged."""

    ROUTES = {
        '/api/v1/user': ('/api/v1/user', 'GITEA_UNAVAILABLE'),
        'tokens': ('/tokens', 'GITEA_UNAVAILABLE'),
        'repository': (f'/api/v1/repos/{fg.REPOSITORY}', 'GITEA_UNAVAILABLE'),
        'branch missing': ('/branches/main', 'POLICY_DRIFT'),
        'branch unreadable': ('/branches/main', 'GITEA_UNAVAILABLE'),
        'pull': ('/pulls/1', 'GITEA_UNAVAILABLE'),
        'files': ('/pulls/1/files', 'GITEA_UNAVAILABLE'),
        'manifest at head': ('/raw/operations/op-0001.json?ref=', 'MANIFEST_INVALID'),
    }

    def test_each_failing_read(self):
        number = self.propose()
        for name, (fragment, code) in self.ROUTES.items():
            with self.subTest(read=name):
                exact = fragment in ('/api/v1/user', f'/api/v1/repos/{fg.REPOSITORY}')
                self.gitea.fail_routes = {} if exact else {fragment: 500 if code != 'POLICY_DRIFT' else 404}
                if exact:
                    original = self.gitea._handle

                    def failing(method, path, headers, body, fragment=fragment, original=original):
                        return self.gitea.reply(500, None) if path == fragment else original(method, path, headers, body)
                    self.gitea._handle = failing
                self.assertRefused(code, self.prepare, number)
                if exact:
                    del self.gitea._handle
        self.gitea.fail_routes = {}
        main = self.gitea.branches['main']
        self.gitea.fail_routes = {f'?ref={main}': 500}
        self.assertRefused('GITEA_UNAVAILABLE', self.prepare, number)
        self.assertEqual(self.gitea.merge_count(), 0)

    def test_no_answer_and_odd_answers(self):
        number = self.propose()

        def unreachable(*args, **kw):
            raise ConnectionRefusedError('nothing listens')

        self.assertRefused('GITEA_UNAVAILABLE', AR.prepare, self.context(http=unreachable), fg.REPOSITORY, number)
        self.gitea.pulls[number]['head_ref'] = 'work/op'
        original = self.gitea.pull_view
        self.gitea.pull_view = lambda n: {**original(n), 'head': {**original(n)['head'], 'sha': 'not a commit'}}
        self.assertRefused('GITEA_UNAVAILABLE', self.prepare, number)
        self.gitea.pull_view = original
        self.gitea.branches['main'] = 'not-a-commit'
        self.assertRefused('GITEA_UNAVAILABLE', self.prepare, number)

    def test_an_operation_already_on_the_protected_branch_without_a_receipt(self):
        base = self.gitea.branches['main']
        self.gitea.advance_main({'operations/op-0001.json': su.manifest()})
        number = self.propose(base=base)
        self.assertRefused('OPERATION_NOT_NEW', self.prepare, number)
        self.assertEqual(AR._receipts(self.store), {})

    def test_prepare_arguments(self):
        number = self.propose()
        self.assertRefused('PULL_NOT_FOUND', self.prepare, 0)
        self.assertRefused('PULL_NOT_FOUND', self.prepare, True)
        for minutes in (0, AR.MAX_EXPIRY_MINUTES + 1, 1.5):
            with self.subTest(minutes=minutes), self.assertRaises(ValueError):
                self.prepare(number, expires_in_minutes=minutes)


class ChallengeState(InMemory):
    def test_a_damaged_challenge_in_the_state_is_refused(self):
        number = self.propose()
        nonce = self.prepare(number)['shown']['nonce']
        path = self.dir / 'state' / 'challenges' / f'{nonce}.json'
        good = json.loads(path.read_text(encoding='utf-8'))
        damaged = {
            'not JSON': '{',
            'a list': '[]',
            'another format': json.dumps({**good, 'format': 'owner-authorization-challenge/v0'}),
            'another nonce': json.dumps({**good, 'shown': {**good['shown'], 'nonce': 'ab' * 16}}),
            'a bad subject': json.dumps({**good, 'subject': {**good['subject'], 'head': 'HEAD'}}),
            'a bad expiry': json.dumps({**good, 'shown': {**good['shown'], 'expiresAt': 'soon'}}),
        }
        for name, text in damaged.items():
            with self.subTest(damage=name):
                path.write_text(text, encoding='utf-8')
                self.assertRefused('CHALLENGE_INVALID', self.record, nonce)
        self.assertEqual(self.gitea.requests_by('POST'), [])


class Store(InMemory):
    """The receipt's reservation is the single use: a race on it refuses the second decision."""

    class Racing:
        def __init__(self, store, mode):
            self.store, self.mode = store, mode

        def __getattr__(self, name):
            return getattr(self.store, name)

        def reserve(self, key, intent, *, actor):
            if self.mode == 'conflict':
                raise su.IS.ConflictingReservation(f'{key} is reserved with another digest')
            if self.mode == 'error':
                raise OSError('the store is unavailable')
            self.store.reserve(key, intent, actor=actor)
            return self.store.reserve(key, intent, actor=actor)

    def test_a_reservation_race_is_refused_before_the_merge(self):
        number = self.propose()
        nonce = self.prepare(number)['shown']['nonce']
        with self.assertRaises(OSError):
            AR.record(self.context(store=self.Racing(self.store, 'error')), nonce, su.statement(),
                      recorded_by=su.RECORDED_BY)
        for mode in ('conflict', 'existing'):
            with self.subTest(mode=mode):
                operation = f'op-{mode}'
                nonce = self.prepare(self.propose(operation, branch=f'work/{mode}'))['shown']['nonce']
                ctx = self.context(store=self.Racing(self.store, mode))
                self.assertRefused('CHALLENGE_CONSUMED', AR.record, ctx, nonce, su.statement(operation),
                                   recorded_by=su.RECORDED_BY)
        self.assertEqual(self.gitea.requests_by('POST'), [])


class Resolve(InMemory):
    def test_a_receipt_left_reserved_is_failed(self):
        number = self.propose()
        nonce = self.prepare(number)['shown']['nonce']
        transition = self.store.transition

        def crash(key, to_state, **kw):
            if to_state == 'dispatched':
                raise OSError('the process ended here')
            return transition(key, to_state, **kw)

        with mock.patch.object(self.store, 'transition', side_effect=crash), self.assertRaises(OSError):
            self.record(nonce)
        self.assertEqual(AR._receipts(self.store)[nonce][0].state, 'reserved')
        result = AR.resolve(self.ctx, nonce)
        self.assertEqual((result['receipt']['state'], result['receipt']['events']), ('failed', ['reserved', 'failed']))
        self.assertEqual(self.gitea.requests_by('POST'), [])

    def test_a_receipt_left_dispatched_is_read(self):
        number = self.propose()
        nonce = self.prepare(number)['shown']['nonce']
        real = self.http

        def crash_on_post(port, path, *, method='GET', **kw):
            if method == 'POST':
                raise RuntimeError('the process ended during the call')
            return real(port, path, method=method, **kw)

        with self.assertRaises(RuntimeError):
            AR.record(self.context(http=crash_on_post), nonce, su.statement(), recorded_by=su.RECORDED_BY)
        self.assertEqual(AR._receipts(self.store)[nonce][0].state, 'dispatched')
        first = AR.resolve(self.ctx, nonce)
        self.assertEqual((first['receipt']['state'], first['changed']), ('unknown', True))
        self.assertIn('until a read finds it merged or closed', first['detail'])
        # Open and not merged stays unknown however long ago the merge was sent.
        self.now = su.NOW + datetime.timedelta(days=365)
        later = AR.resolve(self.ctx, nonce)
        self.assertEqual((later['receipt']['events'], later['changed']), (['reserved', 'dispatched', 'unknown'], False))
        self.gitea.pulls[number]['state'] = 'closed'
        result = AR.resolve(self.ctx, nonce)
        self.assertEqual(result['receipt']['events'], ['reserved', 'dispatched', 'unknown', 'failed'])
        self.assertEqual(self.gitea.merge_count(), 0)

    def test_a_closed_pull_request_and_an_unreadable_one(self):
        number = self.propose()
        nonce = self.prepare(number)['shown']['nonce']
        self.gitea.on_merge = 'drop-before'
        self.assertRefused('OUTCOME_UNKNOWN', self.record, nonce, refusal=False)
        self.gitea.fail_routes = {f'/pulls/{number}': 500}
        self.assertRefused('GITEA_UNAVAILABLE', AR.resolve, self.ctx, nonce)
        self.gitea.fail_routes = {}
        self.gitea.pulls[number]['state'] = 'closed'
        result = AR.resolve(self.ctx, nonce)
        self.assertEqual(result['receipt']['state'], 'failed')
        self.assertRefused('CHALLENGE_INVALID', AR.resolve, self.ctx, 'nonce')
        self.assertEqual(len(self.gitea.requests_by('POST')), 1)


class Codes(unittest.TestCase):
    SOURCE = (su.OWNER_DIR / 'authorization_recorder.py').read_text(encoding='utf-8')

    def test_every_code_has_a_remedy_and_every_remedy_a_code(self):
        raised = set(re.findall(r"RecorderError\(\s*'([A-Z_]+)'", self.SOURCE))
        raised |= set(re.findall(r"code = '([A-Z_]+)' if", self.SOURCE))
        raised |= set(re.findall(r"else '([A-Z_]+)'", self.SOURCE))
        raised |= set(re.findall(r"D\.[A-Z_]+: '([A-Z_]+)'", self.SOURCE))
        raised |= {'POLICY_DRIFT'}
        self.assertEqual(raised - set(AR.REMEDIES), set())
        self.assertEqual(set(AR.REMEDIES) - raised, set())

    def test_the_recorder_never_names_a_token_route_sudo_or_a_forced_merge(self):
        self.assertNotIn("'force_merge'", self.SOURCE)
        self.assertNotIn('merge_when_checks_succeed', self.SOURCE.split('MERGE_BODY_KEYS = ')[1])
        self.assertNotIn("'Sudo'", self.SOURCE)
        self.assertNotIn('generate-access-token', self.SOURCE)
        self.assertNotIn("'POST', '/users", self.SOURCE)

    def test_a_disclosure_is_no_refusal(self):
        self.assertEqual(set(AR.DISCLOSURES), {'PROTECTION_CHANGED_AFTER_MERGE'})
        self.assertEqual(set(AR.DISCLOSURES) & set(AR.REMEDIES), set())
        self.assertNotIn("RecorderError('PROTECTION_CHANGED_AFTER_MERGE'", self.SOURCE)
        self.assertLessEqual({'PROTECTION_UNVERIFIED', 'PROTECTION_DRIFT'}, set(AR.REMEDIES))


class ManagedRootNeverReached(InMemory):
    """A fixture context never reaches the managed data root, its integration store or the platform's
    credential store; a context without its own store or state is refused."""

    def test_a_fixture_context_never_reaches_the_managed_store(self):
        forbid = AssertionError('the managed data root or the platform credential store')
        with mock.patch.object(AR.host.paths, 'resolve', side_effect=forbid), \
                mock.patch.object(AR.host, 'credential_receipts', side_effect=forbid), \
                mock.patch.object(AR.host, 'credential_provider', side_effect=forbid), \
                mock.patch.object(AR, 'managed_context', side_effect=forbid):
            number = self.propose()
            challenge = self.prepare(number)
            result = self.record(challenge['shown']['nonce'])
            AR.resolve(self.ctx, challenge['shown']['nonce'])
            for missing in ({'store': None}, {'state_dir': None}, {'provider': None}, {'port': None}):
                with self.subTest(missing=missing), self.assertRaises(ValueError):
                    AR.prepare(self.context(**missing), fg.REPOSITORY, number)
        self.assertEqual(result['receipt']['state'], 'confirmed')
        self.assertTrue(self.store.path.is_relative_to(self.root))

    def test_the_managed_context_is_built_only_from_the_managed_root(self):
        """managed_context (the command line's) with the managed root, its host record, its store and the
        platform provider all stood in for: the port from the host record, the state under
        <state>/owner-authorization, the provider watched by the act's guard."""
        res = mock.Mock(name='resolution')
        guard = AR.contract.ExposureGuard()

        @contextlib.contextmanager
        def receipts(given):
            self.assertIs(given, res)
            yield self.store

        with mock.patch.object(AR.host.paths, 'resolve', return_value=res), \
                mock.patch.object(AR.host, 'layout', return_value='layout'), \
                mock.patch.object(AR.host, 'read_host_record', return_value={'port': 3456}) as record, \
                mock.patch.object(AR.host.paths, 'ensure', return_value=self.dir / 'managed-state') as ensure, \
                mock.patch.object(AR.host, 'credential_provider', return_value=self.provider), \
                mock.patch.object(AR.host, 'credential_receipts', side_effect=receipts):
            with AR.managed_context(None, guard) as ctx:
                self.assertEqual((ctx.port, ctx.state_dir, ctx.store), (3456, self.dir / 'managed-state', self.store))
                self.assertIsInstance(ctx.provider, AR.contract.WatchedProvider)
                self.assertIsNone(ctx.verifier)  # fail closed: no protection verifier until OA-16's is built
                ctx.provider.get(AR.OWNER_ENTRY)
            with AR.managed_context(4567) as ctx:
                self.assertEqual(ctx.port, 4567)
                self.assertIs(ctx.provider, self.provider)
        ensure.assert_called_with('state', res, 'owner-authorization')
        self.assertEqual(record.call_count, 1)
        self.assertEqual(guard.held, 1)


class CommandLine(InMemory):
    def main(self, *argv):
        out, err = io.StringIO(), io.StringIO()

        @contextlib.contextmanager
        def context(port, guard):
            self.assertIsNone(port)
            yield self.context(provider=AR.contract.WatchedProvider(self.provider, guard))

        code = AR.main(list(argv), out=out, err=err, context=context)
        return code, out.getvalue(), err.getvalue()

    def test_prepare_record_and_resolve(self):
        number = self.propose()
        code, out, err = self.main('prepare', fg.REPOSITORY, str(number))
        self.assertEqual((code, err), (0, ''))
        nonce = json.loads(out)['shown']['nonce']
        said = self.dir / 'statement.json'
        said.write_text(json.dumps(su.statement()), encoding='utf-8')
        code, out, err = self.main('record', '--challenge', nonce, '--statement', str(said),
                                   '--recorded-by', su.RECORDED_BY)
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(json.loads(out)['receipt']['state'], 'confirmed')
        code, out, err = self.main('resolve', '--challenge', nonce)
        self.assertEqual((code, json.loads(out)['changed']), (0, False))
        self.secrets_absent(out, err)

    def test_refusals_and_unknown_outcomes_exit_with_their_codes(self):
        code, out, err = self.main('record', '--recorded-by', su.RECORDED_BY)
        self.assertEqual((code, out), (2, ''))
        self.assertIn('CHALLENGE_MISSING', err)
        self.assertIn('Remedy:', err)
        number = self.propose()
        nonce = json.loads(self.main('prepare', fg.REPOSITORY, str(number))[1])['shown']['nonce']
        said = self.dir / 'statement.json'
        said.write_text(json.dumps(su.statement()), encoding='utf-8')
        self.gitea.on_merge = 'drop-before'
        code, out, err = self.main('record', '--challenge', nonce, '--statement', str(said),
                                   '--recorded-by', su.RECORDED_BY)
        self.assertEqual(code, 1)
        self.assertIn('OUTCOME_UNKNOWN', err)
        code, out, err = self.main('record', '--challenge', nonce, '--statement', str(self.dir / 'absent.json'),
                                   '--recorded-by', su.RECORDED_BY)
        self.assertEqual(code, 2)
        self.assertIn('STATEMENT_INVALID', err)
        self.secrets_absent(out, err)

    def test_without_a_verifier_prepare_reports_and_record_refuses(self):
        self.verifier = None  # as the managed context: no protection verifier
        number = self.propose()
        code, out, err = self.main('prepare', fg.REPOSITORY, str(number))
        self.assertEqual((code, err), (0, ''))
        prepared = json.loads(out)
        self.assertEqual(prepared['protection']['code'], 'PROTECTION_UNVERIFIED')
        said = self.dir / 'statement.json'
        said.write_text(json.dumps(su.statement()), encoding='utf-8')
        code, out, err = self.main('record', '--challenge', prepared['shown']['nonce'], '--statement', str(said),
                                   '--recorded-by', su.RECORDED_BY)
        self.assertEqual((code, out), (2, ''))
        self.assertIn('PROTECTION_UNVERIFIED', err)
        self.assertIn('OA-16', err)
        self.assertEqual(self.gitea.requests_by('POST'), [])
        self.assertEqual(AR._receipts(self.store), {})

    def test_a_disclosure_is_said_and_the_command_succeeds(self):
        number = self.propose()
        nonce = json.loads(self.main('prepare', fg.REPOSITORY, str(number))[1])['shown']['nonce']
        said = self.dir / 'statement.json'
        said.write_text(json.dumps(su.statement()), encoding='utf-8')
        self.verifier.answers = [su.VERIFIED, su.DRIFT]
        code, out, err = self.main('record', '--challenge', nonce, '--statement', str(said),
                                   '--recorded-by', su.RECORDED_BY)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)['receipt']['state'], 'confirmed')
        self.assertIn('PROTECTION_CHANGED_AFTER_MERGE (not a refusal)', err)
        self.assertEqual(self.gitea.merge_count(), 1)

    def test_an_exposed_secret_fails_the_command(self):
        number = self.propose()
        self.gitea.pulls[number]['title'] = f'title holding {fg.PASSWORD}'
        code, out, err = self.main('prepare', fg.REPOSITORY, str(number))
        self.assertEqual((code, out), (1, ''))
        self.assertIn('EXPOSURE_FOUND', err)
        self.assertNotIn(fg.PASSWORD, err)


if __name__ == '__main__':
    unittest.main()
