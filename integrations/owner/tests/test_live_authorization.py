"""The Owner authorization recorder on the live S-01.2.2 fixture (plan leaf P-04.2): opt-in, never by default.

It runs only with AIEH_AUTHZ_RECORDER_LIVE=1 and AIEH_AUTHZ_RECORDER_APPROVAL=<scheme:reference> (where
the Owner's approval of this exercise is kept), on Windows, while the managed Gitea answers and the
Credential Manager entries "AIEH Gitea owner" and "AIEH Gitea bot <role>" (all four roles) exist.
Otherwise it skips with its reason: the ordinary suites never read a credential or write to Gitea.

What it does, on aieh-authz-fixture/authz only (expected outcomes stated in advance):

1. As aieh-bot-builder (its token): two proposal branches work/authz-recorder-<stamp>-a and -b, each
   adding one manifest operations/<id>.json, and a pull request for each into main.
2. As aieh-bot-reviewer (its token): one approving review of each pull request (main requires one).
3. The recorder (the real credential provider: it reads "AIEH Gitea owner" into memory; its own state
   and its integration store in a temporary directory, never the managed root's), pull request A:
   ``prepare``, then ``record`` with a statement attributed to the Owner that names the operation id and
   cites AIEH_AUTHZ_RECORDER_APPROVAL. Expected: exactly one merge commit on main with the base and the
   approved head as parents, the six trailers exactly as written, the manifest digest at the merge,
   merged_by aieh-owner, the receipt confirmed, and aieh-owner still holding zero tokens.
4. Pull request B: ``prepare``; then, after the recorder's checks and before its merge call, the builder
   pushes one more commit to branch B. Expected: Gitea answers 409 to the merge with the challenged
   head_commit_id, nothing is merged, the receipt is failed with HEAD_STALE.
5. Each of the four bot tokens: the same merge call on pull request B (Do: merge, head_commit_id of its
   current head). Expected: 403 or 405 each; main unchanged.
6. Cleanup: the builder closes pull request B. The merge commit of A stays on the fixture's main (a
   protected branch: only a site administrator could rewrite it), and the two work/ branches stay
   (protected branches cannot be deleted). The temporary state and store are removed after step 7.
7. Inspection: the password of aieh-owner (read once more from its entry, in memory) is searched for,
   as UTF-8 and UTF-16LE, in every file of the managed data root, every file git lists in the
   checkout, the exercise's temporary state and store, and this process's environment (inherited from
   the session that runs it). Expected: found nowhere, nothing unreadable. Guest and job environments
   are not reachable from the host and are not scanned here.

AIEH_AUTHZ_RECORDER_REPORT, when set, names a JSON file that receives the observations (statuses, commit
ids, trailers, receipt states; never a credential).
"""
from __future__ import annotations

import base64
import datetime
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

CATEGORY = 'e2e'

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import authz_support as su  # noqa: E402

AR = su.AR
R = AR.roles
G = AR.host
OPT_IN = os.environ.get('AIEH_AUTHZ_RECORDER_LIVE') == '1'
APPROVAL = os.environ.get('AIEH_AUTHZ_RECORDER_APPROVAL', '')
REPORT = os.environ.get('AIEH_AUTHZ_RECORDER_REPORT')
REPOSITORY = f'{R.FIXTURE_ORG}/{R.FIXTURE_REPO}'


def _live():
    if not OPT_IN:
        return None, 'the live recorder exercise is opt-in: AIEH_AUTHZ_RECORDER_LIVE=1 (an Owner-approved act)'
    if not AR.D.REFERENCE.match(APPROVAL):
        return None, 'AIEH_AUTHZ_RECORDER_APPROVAL must name where the Owner approved this exercise (scheme:ref)'
    if os.name != 'nt':
        return None, 'the credentials are in Windows Credential Manager'
    try:
        res = G.paths.resolve()
        port = G.read_host_record(G.layout(res))['port']
    except (G.GiteaError, G.paths.PathsError) as exc:
        return None, f'Gitea is not installed here ({exc})'
    if not G.healthy(port):
        return None, 'Gitea is not running (task gitea:up)'
    provider = G.credential_provider()
    tokens = {role: R.read_token(provider, role) for role in R.ROLES}
    if missing := sorted(role for role, token in tokens.items() if token is None):
        return None, f'no Credential Manager entry for {missing}'
    return (port, provider, tokens), None


class LiveExercise(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        found, reason = _live()
        if found is None:
            raise unittest.SkipTest(reason)
        cls.port, cls.provider, cls.tokens = found
        cls._tmp = tempfile.TemporaryDirectory(prefix='aieh-authz-live-')
        cls.root = Path(cls._tmp.name)
        cls.observed = {}

    @classmethod
    def tearDownClass(cls):
        if REPORT:
            Path(REPORT).write_text(json.dumps(cls.observed, indent=1, default=str) + '\n', encoding='utf-8')
        cls._tmp.cleanup()

    def bot(self, role):
        return R.Api(self.port, self.tokens[role])

    def propose(self, branch, operation):
        manifest = su.manifest(operation, target='aieh-authz-fixture (live recorder exercise; no effect)',
                               expiresAt=(datetime.datetime.now(datetime.timezone.utc)
                                          + datetime.timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M:%SZ'))
        status, body = self.bot('builder').call('POST', f'/repos/{REPOSITORY}/contents/operations/{operation}.json', {
            'content': base64.b64encode(manifest).decode('ascii'), 'message': f'Propose operation {operation}',
            'branch': R.DEFAULT_BRANCH, 'new_branch': branch})
        self.assertEqual(status, 201, body)
        status, pull = self.bot('builder').call('POST', f'/repos/{REPOSITORY}/pulls', {
            'head': branch, 'base': R.DEFAULT_BRANCH, 'title': f'Live recorder exercise: {operation}'})
        self.assertEqual(status, 201, pull)
        status, review = self.bot('reviewer').call('POST', f'/repos/{REPOSITORY}/pulls/{pull["number"]}/reviews',
                                                   {'event': 'APPROVED', 'body': 'live recorder exercise'})
        self.assertEqual(status, 200, review)
        return pull['number']

    def main_head(self):
        status, body = self.bot('verifier').call('GET', f'/repos/{REPOSITORY}/branches/{R.DEFAULT_BRANCH}')
        self.assertEqual(status, 200, body)
        return body['commit']['id']

    def test_one_recorded_decision_one_merge_then_409_and_bot_refusals(self):
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dt%H%M%Sz')
        store = su.IS.open_store(self.root / 'integration.sqlite')
        self.addCleanup(store.close)
        ctx = AR.Context(self.root / 'state', store, self.provider, self.port)
        # A: one recorded decision, one merge
        op_a = f'live-{stamp}-a'
        pull_a = self.propose(f'work/authz-recorder-{stamp}-a', op_a)
        before = self.main_head()
        challenge = AR.prepare(ctx, REPOSITORY, pull_a)
        said = {'text': f'Live exercise approved by the Owner ({APPROVAL}): authorize fixture operation {op_a}.',
                'attributedTo': 'owner', 'channel': 'main-session', 'reference': APPROVAL}
        result = AR.record(ctx, challenge['shown']['nonce'], said, recorded_by='agent:live-exercise')
        after = self.main_head()
        self.observed['A'] = {'pull': pull_a, 'before': before, 'after': after, 'merge': result['merge'],
                              'receipt': result['receipt'], 'decision': result['decision']['decisionId']}
        self.assertEqual(result['merge']['mergeCommit'], after)
        self.assertEqual(result['merge']['parents'], [before, challenge['subject']['head']])
        self.assertEqual(result['merge']['trailers'], AR.trailers(result['decision'], challenge['subject']['head'],
                                                                  challenge['subject']['digest']))
        self.assertEqual(result['receipt']['state'], 'confirmed')
        session = AR.open_session(ctx)  # zero tokens on aieh-owner afterwards (the identity check)
        session.close()
        # B: the head moves after the checks; Gitea answers 409
        op_b = f'live-{stamp}-b'
        branch_b = f'work/authz-recorder-{stamp}-b'
        pull_b = self.propose(branch_b, op_b)
        challenge_b = AR.prepare(ctx, REPOSITORY, pull_b)
        read = AR.read_proposal

        def then_move_the_head(*args, **kw):
            proposal = read(*args, **kw)
            status, body = self.bot('builder').call('POST', f'/repos/{REPOSITORY}/contents/operations/{op_b}.txt', {
                'content': base64.b64encode(b'moved after the checks\n').decode('ascii'),
                'message': 'Move the head after the checks', 'branch': branch_b})
            self.assertEqual(status, 201, body)
            return proposal

        AR.read_proposal = then_move_the_head
        try:
            with self.assertRaises(AR.RecorderError) as caught:
                AR.record(ctx, challenge_b['shown']['nonce'], {**said, 'text': said['text'].replace(op_a, op_b)},
                          recorded_by='agent:live-exercise')
        finally:
            AR.read_proposal = read
        self.observed['B'] = {'pull': pull_b, 'code': caught.exception.code, 'detail': caught.exception.detail,
                              'main': self.main_head()}
        self.assertEqual(caught.exception.code, 'HEAD_STALE')
        self.assertIn('409', caught.exception.detail)
        self.assertEqual(self.main_head(), after)
        # every bot token, on the merge itself
        status, pr = self.bot('verifier').call('GET', f'/repos/{REPOSITORY}/pulls/{pull_b}')
        bots = {}
        for role in R.ROLES:
            status, body = self.bot(role).call('POST', f'/repos/{REPOSITORY}/pulls/{pull_b}/merge',
                                               {'Do': 'merge', 'head_commit_id': pr['head']['sha']})
            bots[role] = status
        self.observed['bots'] = bots
        self.assertTrue(all(status in (403, 405) for status in bots.values()), bots)
        self.assertEqual(self.main_head(), after)
        status, _ = self.bot('builder').call('PATCH', f'/repos/{REPOSITORY}/pulls/{pull_b}', {'state': 'closed'})
        self.observed['cleanup'] = {'close_b': status}
        # the inspection: the Owner credential is in its provider entry only
        self.observed['inspection'] = inspection = inspect_custody(self.provider, self.root)
        self.assertEqual(inspection['found'], [], inspection)
        self.assertEqual(inspection['unreadable'], [], inspection)


def inspect_custody(provider, scratch):
    """Where aieh-owner's password is, besides its provider entry: every file of the managed data root (the
    recorder's state and the integration store included), every file git lists in the checkout, this
    exercise's temporary state and store, and the environment of this process (which inherits the
    session's). File names only; the password is held in memory for the scan and dropped."""
    entry = provider.get(AR.OWNER_ENTRY)
    needles = [entry[1].encode('utf-8')]
    del entry
    try:
        root = G.paths.resolve().root
        managed = G.contains_secret(Path(str(root)), needles)
        checkout = G.files_containing(G.checkout_files(su.REPO), needles)
        temporary = G.contains_secret(Path(scratch), needles)
        environment = [name for name, value in os.environ.items()
                       if any(n in value.encode('utf-8', 'replace') for n in needles)]
    finally:
        needles.clear()
    return {'found': managed['found'] + checkout['found'] + temporary['found'] + environment,
            'unreadable': managed['unreadable'] + checkout['unreadable'] + temporary['unreadable'],
            'scanned': {'managed root': 'every file', 'checkout': 'git ls-files --cached --others --exclude-standard',
                        'temporary state and store': 'every file', 'environment': 'this process'}}


if __name__ == '__main__':
    unittest.main()
