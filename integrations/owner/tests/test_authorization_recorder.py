"""The Owner authorization recorder (plan leaf P-04.2) against an in-process fake Gitea HTTP server.

Run from the repository root, under the tools interpreter:

    <tools python> -I -B -m unittest discover -s integrations/owner/tests -v

The plan's proof, over real HTTP on host loopback (fake_gitea.Server, one per module): a recorded
decision gives exactly one merge, bound to the approved head and the manifest digest, with an
integration-store receipt and the trailers; each of these is refused with its stable code and no merge:
a stale head (Gitea's 409, and the recorder's own check before it), an altered digest, a replayed or
expired decision, a missing or non-Owner statement, a missing challenge, protection drift and a token on
aieh-owner; no token is minted; every bot token is refused both as the recorder's input and for the
merge; and a lost answer is resolved as unknown by reading, never by merging again. The fake Gitea, its
password and its tokens are synthetic; every statement is synthetic and no Owner decision.
"""
import datetime
import json
import sys
import unittest
from pathlib import Path

CATEGORY = 'integration'

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import authz_support as su  # noqa: E402

AR, D, fg = su.AR, su.D, su.fg
SERVER = None


def setUpModule():
    global SERVER
    SERVER = fg.Server()


def tearDownModule():
    SERVER.close()


class OverHttp(su.Fixture):
    def gitea_for_test(self):
        return None, SERVER.port, SERVER.reset()  # the recorder's own keep-alive connection

    def assertNoMerge(self):
        self.assertEqual(self.gitea.merge_count(), 0)
        self.assertEqual(self.gitea.branches['main'], self.base)

    def setUp(self):
        super().setUp()
        self.base = self.gitea.branches['main']

    def ready(self, operation=su.OPERATION, **kw):
        """A proposal and its challenge."""
        number = self.propose(operation, **kw)
        return number, self.prepare(number)


class Authorized(OverHttp):
    """A recorded decision gives exactly one merge, bound to the approved head and digest, with a receipt
    and the trailers."""

    def test_one_merge_bound_to_the_head_and_digest_with_receipt_and_trailers(self):
        number, challenge = self.ready()
        head = self.gitea.head(number)
        nonce = challenge['shown']['nonce']
        digest = 'sha256:' + __import__('hashlib').sha256(su.manifest()).hexdigest()
        self.assertEqual((challenge['subject']['head'], challenge['subject']['digest']), (head, digest))
        self.now = su.LATER
        result = self.record(nonce, new_decision_id=lambda: '1f0e2d3c-4b5a-4968-8776-0123456789ab')
        decision = result['decision']
        # exactly one merge: a merge commit of the protected branch's head and the approved head
        self.assertEqual(self.gitea.merge_count(), 1)
        merge = self.gitea.branches['main']
        self.assertEqual(self.gitea.commits[merge]['parents'], [self.base, head])
        self.assertEqual(result['merge']['mergeCommit'], merge)
        self.assertEqual(result['merge']['parents'], [self.base, head])
        self.assertEqual(result['merge']['digest'], digest)
        self.assertEqual(result['merge']['mergedBy'], AR.OWNER)
        self.assertEqual(result['display'], f'merged under Owner authority by the recorder on decision '
                                            f'{decision["decisionId"]}')
        # the trailers, in the merge commit as Gitea wrote it
        message = self.gitea.commits[merge]['message']
        self.assertEqual(AR.parse_trailers(message), {
            'AIEH-Decision-Id': decision['decisionId'], 'AIEH-Decision-Channel': 'main-session',
            'AIEH-Approved-Head': head, 'AIEH-Manifest-Digest': digest,
            'AIEH-Statement-Ref': 'conversation:fixture-owner/message-9', 'AIEH-Recorder': 'authorization-recorder/1'})
        self.assertTrue(message.startswith(f'Authorize operation {su.OPERATION} (Owner decision '))
        # the merge call: Do merge with head_commit_id; no force, no auto-merge, no sudo, basic auth only
        self.assertEqual(len(self.gitea.merge_bodies), 1)
        body = self.gitea.merge_bodies[0]
        self.assertEqual(tuple(body), AR.MERGE_BODY_KEYS)
        self.assertEqual((body['Do'], body['head_commit_id'], body['delete_branch_after_merge']),
                         ('merge', head, False))
        self.assertNotIn('force_merge', body)
        self.assertNotIn('merge_when_checks_succeed', body)
        self.assertEqual({(r['auth'], r['doer'], r['sudo']) for r in self.gitea.requests},
                         {('basic', AR.OWNER, False)})
        # no token minted: the only POST is the merge; tokens are only listed
        self.assertEqual([r['path'] for r in self.gitea.requests_by('POST')],
                         [f'/api/v1/repos/{fg.REPOSITORY}/pulls/{number}/merge'])
        self.assertEqual({r['method'] for r in self.gitea.requests if r['path'].endswith('/tokens')}, {'GET'})
        self.assertEqual(self.gitea.users[AR.OWNER]['tokens'], [])
        # the Owner decision record (the shared shape) and the write-ahead receipt
        self.assertEqual(D.check_record(decision), [])
        self.assertEqual(decision['kind'], 'authorize-operation')
        self.assertEqual(list(decision), list(D.FIELDS))
        self.assertEqual(decision['subject']['head'], head)
        saved = (self.dir / 'state' / 'decisions' / f'{decision["decisionId"]}.json').read_text(encoding='utf-8')
        self.assertEqual(json.loads(saved), decision)
        key = AR.RECEIPT_PREFIX + nonce
        self.assertEqual(result['receipt']['operation_key'], key)
        self.assertEqual(self.receipts(), {nonce: ('confirmed', ['reserved', 'dispatched', 'confirmed'])})
        intent = json.loads(self.store.get(key).intent_json)
        self.assertEqual(intent['format'], 'aieh-owner-authorization/1')
        self.assertEqual(intent['decision'], decision)
        self.assertEqual((intent['approvedHead'], intent['digest'], intent['baseHead']), (head, digest, self.base))
        confirmed = json.loads(self.store.events(key)[-1].detail_json)
        self.assertEqual(confirmed['mergeCommit'], merge)
        self.secrets_absent(json.dumps(result))

    def test_the_receipt_is_written_before_the_merge_is_sent(self):
        number, challenge = self.ready()
        nonce, seen = challenge['shown']['nonce'], []
        merge = self.gitea.merge

        def observe(*args):  # in the server's thread: a connection of its own to the store
            with su.IS.open_store(self.store.path) as store:
                reservation = store.get(AR.RECEIPT_PREFIX + nonce)
                seen.append((reservation.state, [e.to_state for e in store.events(reservation.operation_key)]))
            return merge(*args)

        self.gitea.merge = observe
        self.record(nonce)
        self.assertEqual(seen, [('dispatched', ['reserved', 'dispatched'])])


class StaleHead(OverHttp):
    def test_gitea_409_when_the_head_moves_after_the_checks(self):
        number, challenge = self.ready()
        self.gitea.on_merge = 'move-head'
        error = self.assertRefused('HEAD_STALE', self.record, challenge['shown']['nonce'], refusal=False)
        self.assertIn('409', error.detail)
        self.assertNoMerge()
        self.assertEqual(self.receipts(), {challenge['shown']['nonce']: ('failed', ['reserved', 'dispatched', 'failed'])})

    def test_the_recorder_refuses_a_moved_head_before_sending(self):
        number, challenge = self.ready()
        self.gitea.push_to_head(number, {'notes.txt': b'later\n'})
        self.assertRefused('HEAD_STALE', self.record, challenge['shown']['nonce'])
        self.assertNoMerge()
        self.assertEqual(self.gitea.requests_by('POST'), [])
        self.assertEqual(self.receipts(), {})


class AlteredDigest(OverHttp):
    def test_an_altered_digest_is_refused(self):
        number, challenge = self.ready()
        nonce = challenge['shown']['nonce']
        path = self.dir / 'state' / 'challenges' / f'{nonce}.json'
        challenge['subject']['digest'] = 'sha256:' + '0' * 64
        path.write_text(json.dumps(challenge, indent=2) + '\n', encoding='utf-8', newline='\n')
        self.assertRefused('DIGEST_CHANGED', self.record, nonce)
        self.assertNoMerge()
        self.assertEqual(self.gitea.requests_by('POST'), [])


class ReplayedOrExpired(OverHttp):
    def test_a_replayed_decision_is_refused(self):
        number, challenge = self.ready()
        nonce = challenge['shown']['nonce']
        self.record(nonce)
        self.assertRefused('CHALLENGE_CONSUMED', self.record, nonce)
        self.assertEqual(self.gitea.merge_count(), 1)
        # the same operation on a new proposal: already on the protected branch
        again = self.propose(branch='work/again', base=self.base)
        self.assertRefused('OPERATION_NOT_NEW', self.prepare, again)
        self.assertEqual(len(self.gitea.requests_by('POST')), 1)

    def test_a_second_challenge_for_an_operation_with_a_live_receipt_is_refused(self):
        number, first = self.ready()
        second = self.prepare(number)
        self.gitea.on_merge = 'drop-before'
        self.assertRefused('OUTCOME_UNKNOWN', self.record, first['shown']['nonce'], refusal=False)
        self.assertRefused('OPERATION_NOT_NEW', self.record, second['shown']['nonce'])
        self.assertEqual(len(self.gitea.requests_by('POST')), 1)
        self.assertNoMerge()

    def test_an_expired_challenge_is_refused(self):
        number, challenge = self.ready()
        self.now = su.NOW + datetime.timedelta(minutes=AR.DEFAULT_EXPIRY_MINUTES)
        self.assertRefused('CHALLENGE_EXPIRED', self.record, challenge['shown']['nonce'])
        self.assertNoMerge()
        self.assertEqual(self.gitea.requests_by('POST'), [])

    def test_an_expired_manifest_is_refused(self):
        number, challenge = self.ready(files={'operations/op-0001.json': su.manifest(expiresAt='2026-11-10T12:10:00Z')})
        self.now = su.NOW + datetime.timedelta(minutes=10)
        self.assertRefused('MANIFEST_EXPIRED', self.record, challenge['shown']['nonce'])
        self.assertNoMerge()
        self.assertEqual(self.gitea.requests_by('POST'), [])


class Statement(OverHttp):
    """Authenticity: missing or non-Owner statements, the operation id, the channel; nothing is sent."""

    def test_each_statement_refusal(self):
        number, challenge = self.ready()
        nonce = challenge['shown']['nonce']
        before = len(self.gitea.requests)
        cases = [
            ('STATEMENT_MISSING', None),
            ('STATEMENT_MISSING', su.statement(text='')),
            ('STATEMENT_MISSING', su.statement(reference='missing:the reply')),
            ('STATEMENT_NOT_OWNER', su.statement(attributedTo='person:someone')),
            ('STATEMENT_MODEL_AUTHORED', su.statement(attributedTo='agent:overseer')),
            ('STATEMENT_MODEL_AUTHORED', su.statement(reference='openhands:conversation/1')),
            ('STATEMENT_INVALID', su.statement(channel='Main Session')),
            ('CHANNEL_NOT_ADMITTED', su.statement(channel='email')),
            ('STATEMENT_OPERATION_MISSING', su.statement(text='Yes, go ahead.')),
            ('STATEMENT_OPERATION_MISSING', su.statement(text='I authorize operation op-00012.')),
        ]
        for code, said in cases:
            with self.subTest(code=code, said=said):
                if said is None:
                    self.assertRefused(code, AR.record, self.ctx, nonce, None, recorded_by=su.RECORDED_BY)
                else:
                    self.assertRefused(code, self.record, nonce, said)
        self.assertRefused('RECORDED_BY_INVALID', self.record, nonce, recorded_by='the overseer')
        self.assertEqual(len(self.gitea.requests), before)
        self.assertNoMerge()
        self.assertEqual(self.receipts(), {})


class Challenge(OverHttp):
    def test_a_missing_or_foreign_challenge_is_refused(self):
        number, challenge = self.ready()
        before = len(self.gitea.requests)
        self.assertRefused('CHALLENGE_MISSING', self.record, None)
        self.assertRefused('CHALLENGE_MISSING', self.record, '')
        self.assertRefused('CHALLENGE_INVALID', self.record, 'not-a-nonce')
        self.assertRefused('CHALLENGE_UNKNOWN', self.record, 'ab' * 16)
        self.assertEqual(len(self.gitea.requests), before)
        self.assertNoMerge()


class PolicyDrift(OverHttp):
    """What aieh-owner can observe of the repository and its protected branch must be the expected policy."""

    DRIFTS = {
        'protection removed': lambda g: g.protection.pop('main'),
        'aieh-owner may push': lambda g: g.protection['main']['push_whitelist'].append(fg.OWNER),
        'aieh-owner off the merge allowlist': lambda g: g.protection['main']['merge_whitelist'].remove(fg.OWNER),
        'approvals lowered': lambda g: g.protection['main'].update(required_approvals=0),
        'status checks changed': lambda g: g.protection['main'].update(enable_status_check=True),
        'merge commits disallowed': lambda g: g.repo.update(allow_merge_commits=False),
        'aieh-owner a repository administrator': lambda g: g.permissions[fg.OWNER].update(admin=True),
        'repository made public': lambda g: g.repo.update(private=False),
    }

    def test_each_drift_is_refused(self):
        for name, drift in self.DRIFTS.items():
            with self.subTest(drift=name):
                self.gitea = SERVER.reset()
                self.base = self.gitea.branches['main']
                number, challenge = self.ready(branch=f'work/{len(self.gitea.requests)}')
                drift(self.gitea)
                error = self.assertRefused('POLICY_DRIFT', self.record, challenge['shown']['nonce'])
                self.assertNoMerge()
                self.assertEqual(self.gitea.requests_by('POST'), [])
                self.assertTrue(error.detail)


class OwnerIdentity(OverHttp):
    def test_a_token_on_aieh_owner_is_refused(self):
        number, challenge = self.ready()
        self.gitea.users[fg.OWNER]['tokens'].append('a-leftover-token')
        self.assertRefused('OWNER_HAS_TOKEN', self.record, challenge['shown']['nonce'])
        self.assertRefused('OWNER_HAS_TOKEN', self.prepare, number)
        self.assertNoMerge()
        self.assertEqual(self.gitea.requests_by('POST'), [])

    def test_an_administrator_aieh_owner_is_refused(self):
        number, challenge = self.ready()
        self.gitea.users[fg.OWNER]['is_admin'] = True
        self.assertRefused('OWNER_IS_ADMIN', self.record, challenge['shown']['nonce'])
        self.assertNoMerge()

    def test_a_rejected_password_is_refused(self):
        number, challenge = self.ready()
        self.gitea.users[fg.OWNER]['password'] = 'changed'
        self.assertRefused('CREDENTIAL_REJECTED', self.record, challenge['shown']['nonce'])
        self.assertNoMerge()


class BotTokens(OverHttp):
    """Every bot token is refused as the recorder's input and for the merge."""

    def test_every_bot_token_is_refused_as_input_and_for_the_merge(self):
        number, challenge = self.ready()
        nonce = challenge['shown']['nonce']
        for bot, token in fg.BOT_TOKENS.items():
            with self.subTest(bot=bot, entry='the bot and its token'):
                before = len(self.gitea.requests)
                self.provider.entries[AR.OWNER_ENTRY] = (bot, token)
                self.assertRefused('CREDENTIAL_REFUSED', self.record, nonce)
                self.assertEqual(len(self.gitea.requests), before)
            with self.subTest(bot=bot, entry='aieh-owner with the bot token'):
                self.provider.entries[AR.OWNER_ENTRY] = (fg.OWNER, token)
                self.assertRefused('CREDENTIAL_REFUSED', self.record, nonce)
                self.assertEqual(len(self.gitea.requests), before)
            with self.subTest(bot=bot, entry='a password that signs in as the bot'):
                self.provider.entries[AR.OWNER_ENTRY] = (fg.OWNER, f'password of {bot}')
                self.gitea.basic_as[(fg.OWNER, f'password of {bot}')] = bot
                self.assertRefused('IDENTITY_NOT_OWNER', self.record, nonce)
            with self.subTest(bot=bot, entry='the bot token on the merge itself'):
                status, _h, raw = AR.host.http_get(
                    SERVER.port, f'/api/v1/repos/{fg.REPOSITORY}/pulls/{number}/merge', method='POST',
                    body=json.dumps({'Do': 'merge', 'head_commit_id': self.gitea.head(number)}).encode(),
                    headers={'Authorization': f'token {token}', 'Content-Type': 'application/json'})
                self.assertEqual(status, 405, raw)
        self.assertNoMerge()
        recorder_calls = [r for r in self.gitea.requests if r['auth'] != 'token']
        self.assertEqual({r['auth'] for r in recorder_calls}, {'basic'})
        self.assertEqual(self.receipts(), {})
        self.secrets_absent()


class Binding(OverHttp):
    def test_what_can_never_be_authorized_is_refused_at_prepare(self):
        cases = {
            'PULL_AUTHOR_OWNER': dict(author=fg.OWNER),
            'MANIFEST_NOT_SINGLE': dict(files={'operations/op-0001.json': su.manifest(), 'README.md': b'x\n'}),
            'PULL_NOT_OPEN': dict(state='closed'),
            'MANIFEST_INVALID': dict(files={'operations/op-0001.json': su.manifest(operation='op-0002')}),
        }
        for code, kw in cases.items():
            with self.subTest(code=code):
                number = self.propose(branch=f'work/{code.lower()}', **kw)
                self.assertRefused(code, self.prepare, number)
        self.assertRefused('PULL_NOT_FOUND', self.prepare, 99)
        self.assertRefused('REPOSITORY_NOT_ADMITTED', AR.prepare, self.ctx, 'someone/else', 1)
        foreign = self.propose(branch='work/fork')
        self.gitea.pulls[foreign]['head_repo'] = 'someone/fork'
        self.assertRefused('PULL_BASE_WRONG', self.prepare, foreign)
        self.assertFalse((self.dir / 'state' / 'challenges').exists())
        self.assertNoMerge()

    def test_an_unmergeable_pull_request_is_refused_at_record(self):
        number, challenge = self.ready()
        self.gitea.pulls[number]['mergeable'] = False
        self.assertRefused('PULL_NOT_MERGEABLE', self.record, challenge['shown']['nonce'])
        self.assertNoMerge()


class LostAnswer(OverHttp):
    """A lost answer is unknown, and resolve reads the ref; it never merges again."""

    def test_merged_but_the_answer_was_lost(self):
        for mode in ('drop', 'error-after'):
            with self.subTest(mode=mode):
                self.gitea = SERVER.reset()
                operation = f'op-{mode}'
                number, challenge = self.ready(operation, branch=f'work/{mode}')
                nonce = challenge['shown']['nonce']
                self.gitea.on_merge = mode
                self.assertRefused('OUTCOME_UNKNOWN', self.record, nonce, su.statement(operation), refusal=False)
                self.assertEqual(self.receipts()[nonce], ('unknown', ['reserved', 'dispatched', 'unknown']))
                self.assertEqual(self.gitea.merge_count(), 1)
                self.gitea.on_merge = None
                result = AR.resolve(self.ctx, nonce)
                self.assertEqual(result['receipt']['state'], 'confirmed')
                self.assertEqual(self.receipts()[nonce][1], ['reserved', 'dispatched', 'unknown', 'confirmed'])
                self.assertEqual(len(self.gitea.requests_by('POST')), 1)
                self.assertEqual(self.gitea.merge_count(), 1)
                self.assertRefused('CHALLENGE_CONSUMED', self.record, nonce)

    def test_not_merged_and_the_answer_was_lost(self):
        number, challenge = self.ready()
        nonce = challenge['shown']['nonce']
        self.gitea.on_merge = 'drop-before'
        self.assertRefused('OUTCOME_UNKNOWN', self.record, nonce, refusal=False)
        self.gitea.on_merge = None
        early = AR.resolve(self.ctx, nonce)
        self.assertEqual((early['receipt']['state'], early['changed']), ('unknown', False))
        self.now = su.NOW + datetime.timedelta(minutes=AR.SETTLE_MINUTES)
        late = AR.resolve(self.ctx, nonce)
        self.assertEqual(late['receipt']['state'], 'failed')
        self.assertEqual(len(self.gitea.requests_by('POST')), 1)
        self.assertNoMerge()
        self.assertEqual(AR.resolve(self.ctx, nonce)['changed'], False)
        self.assertRefused('RECEIPT_MISSING', AR.resolve, self.ctx, 'cd' * 16)

    def test_merged_by_something_else_is_failed_not_confirmed(self):
        number, challenge = self.ready()
        nonce = challenge['shown']['nonce']
        self.gitea.on_merge = 'drop-before'
        self.assertRefused('OUTCOME_UNKNOWN', self.record, nonce, refusal=False)
        self.gitea.on_merge = None
        self.gitea.merge(number, fg.OWNER, {'Do': 'merge', 'merge_title_field': 'an unrecorded merge'})
        result = AR.resolve(self.ctx, nonce)
        self.assertEqual(result['receipt']['state'], 'failed')
        detail = json.loads(self.store.events(AR.RECEIPT_PREFIX + nonce)[-1].detail_json)
        self.assertEqual(detail['code'], 'MERGED_OTHERWISE')
        self.assertEqual(len(self.gitea.requests_by('POST')), 1)


if __name__ == '__main__':
    unittest.main()
