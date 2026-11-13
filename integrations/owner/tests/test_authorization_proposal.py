"""The proposal act of the authorization repository (plan leaf E-05.7; decision 0022 point 4), offline.

Run from the repository root, under the tools interpreter:

    <tools python> -I -B -m unittest discover -s integrations/owner/tests -v

Against the fake Gitea of fake_gitea.py, called in memory (no socket), serving the S-01.2.2 fixture in an exercise
context and, in the second class, the authorization repository in a context admitting what the command line's does.
Covered: one pull request from work/<id> into main, opened by the proposing bot and approved by the reviewer bot,
whose only change is the added operations/<id>.json with the given bytes (sha256 equal on read-back), with bot
tokens only and never a merge; the recorder prepares exactly it; an existing operation id refused (on main, its
branch present, in an open pull request) before anything is written; a read-back that differs is not approved;
the credential refusals; the session's routes; the command line. Every value is synthetic.
"""
import base64
import contextlib
import hashlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

CATEGORY = 'unit'

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import authz_support as su  # noqa: E402

AR, fg = su.AR, su.fg
PR = su._load('authorization_proposal', su.OWNER_DIR / 'authorization_proposal.py')
R = AR.roles
BUILDER, REVIEWER = R.ROLES['builder']['user'], R.ROLES['reviewer']['user']
MANIFEST = f'operations/{su.OPERATION}.json'


def setUpModule():
    su.start()


def tearDownModule():
    su.stop()


def bot_entries(**changes):
    entries = {R.target('builder'): (BUILDER, fg.BOT_TOKENS[BUILDER]),
               R.target('reviewer'): (REVIEWER, fg.BOT_TOKENS[REVIEWER])}
    entries.update(changes)
    return entries


class Proposal(su.Fixture):
    """On the S-01.2.2 fixture, in an exercise context."""

    def gitea_for_test(self):
        gitea = fg.FakeGitea(self.repository)
        return gitea, 3000, gitea

    def setUp(self):
        super().setUp()
        self.bots = fg.FixtureProvider(bot_entries())
        self.main_before = self.gitea.branches['main']

    def pctx(self, **changes):
        fields = dict(provider=self.bots, port=3000, policies=self.admitted(), http=self.gitea)
        fields.update(changes)
        return PR.Context(**fields)

    def propose(self, blob=None, repository=None, **changes):
        return PR.propose(self.pctx(**changes), repository or self.repository,
                          su.manifest() if blob is None else blob)

    def refused(self, code, *args, refusal=True, **kw):
        with self.assertRaises(PR.ProposalError) as caught:
            self.propose(*args, **kw)
        self.assertEqual((caught.exception.code, caught.exception.refusal), (code, refusal), caught.exception.detail)
        self.assertIn(code, PR.REMEDIES)
        return caught.exception

    def writes(self):
        return [(r['method'], r['path']) for r in self.gitea.requests if r['method'] != 'GET']

    def assertNothingWritten(self):
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.gitea.branches['main'], self.main_before)
        self.assertEqual(self.gitea.merge_count(), 0)

    def test_one_pull_request_from_work_into_main_whose_only_change_is_the_manifest(self):
        blob = su.manifest()
        result = self.propose(blob)
        self.assertEqual(len(self.gitea.pulls), 1)
        number, pr = next(iter(self.gitea.pulls.items()))
        head = self.gitea.head(number)
        self.assertEqual((pr['state'], pr['merged'], pr['user'], pr['base'], pr['head_ref'], pr['head_repo']),
                         ('open', False, BUILDER, 'main', f'work/{su.OPERATION}', self.repository))
        self.assertEqual(self.gitea.files(number), [{'filename': MANIFEST, 'status': 'added'}])
        self.assertEqual(self.gitea.commits[head]['tree'][MANIFEST], blob)  # the given bytes
        digest = 'sha256:' + hashlib.sha256(blob).hexdigest()
        self.assertEqual(result, {
            'repository': self.repository, 'operation': su.OPERATION, 'kind': 'example-effect', 'manifest': MANIFEST,
            'digest': digest, 'branch': f'work/{su.OPERATION}', 'base': 'main', 'baseHead': self.main_before,
            'pull': number, 'head': head, 'proposedBy': BUILDER, 'approvedBy': REVIEWER})
        # approved by the reviewer bot, of exactly that head; never merged
        self.assertEqual(pr['reviews'], [(REVIEWER, 'APPROVED', head)])
        self.assertEqual((self.gitea.merge_count(), self.gitea.branches['main']), (0, self.main_before))
        # bot tokens only: every request a bot's token; the writes are the file, the pull request and the approval
        self.assertEqual({(r['auth'], r['doer'], r['sudo']) for r in self.gitea.requests},
                         {('token', BUILDER, False), ('token', REVIEWER, False)})
        repo = f'/api/v1/repos/{self.repository}'
        self.assertEqual(self.writes(), [('POST', f'{repo}/contents/{MANIFEST}'), ('POST', f'{repo}/pulls'),
                                         ('POST', f'{repo}/pulls/{number}/reviews')])
        self.assertEqual([(r['method'], r['path']) for r in self.gitea.requests if r['doer'] == REVIEWER],
                         [('GET', '/api/v1/token'), ('POST', f'{repo}/pulls/{number}/reviews')])
        self.assertFalse(any('/merge' in r['path'] or '/user' in r['path'] for r in self.gitea.requests))
        self.assertEqual(self.bots.reads, [R.target('builder'), R.target('reviewer')])
        self.assertEqual(self.provider.reads, [])  # aieh-owner's entry is never read by the act
        for token in fg.BOT_TOKENS.values():
            self.assertNotIn(token, json.dumps(result))
        # the authorization recorder prepares exactly this proposal
        challenge = self.prepare(number)
        self.assertEqual((challenge['subject']['head'], challenge['subject']['digest'], challenge['subject']['author']),
                         (head, digest, BUILDER))

    def test_an_existing_operation_id_is_refused_before_anything_is_written(self):
        cases = {
            'on main': lambda g: g.advance_main({MANIFEST: su.manifest()}),
            'its branch present': lambda g: g.branches.update({f'work/{su.OPERATION}': g.branches['main']}),
            'in an open pull request': lambda g: g.propose({MANIFEST: su.manifest()}, branch='work/another'),
        }
        for name, existing in cases.items():
            with self.subTest(existing=name):
                self.gitea = fg.FakeGitea(self.repository)
                existing(self.gitea)
                self.main_before, pulls = self.gitea.branches['main'], dict(self.gitea.pulls)
                self.refused('OPERATION_NOT_NEW')
                self.assertNothingWritten()
                self.assertEqual(self.gitea.pulls, pulls)
        self.gitea = fg.FakeGitea(self.repository)
        self.main_before = self.gitea.branches['main']
        self.propose()
        self.refused('OPERATION_NOT_NEW')  # the same id again
        self.assertEqual(len(self.gitea.pulls), 1)

    def test_a_read_back_that_differs_is_not_approved(self):
        original_create, original_files, original_view = (self.gitea.create_file, self.gitea.files,
                                                           self.gitea.pull_view)

        def altered(path, doer, form):
            content = base64.b64decode(form['content']) + b' '
            return original_create(path, doer, {**form, 'content': base64.b64encode(content).decode()})

        damages = {
            'DIGEST_CHANGED': ('create_file', altered),
            'MANIFEST_NOT_SINGLE': ('files', lambda n: [*original_files(n), {'filename': 'README.md',
                                                                              'status': 'modified'}]),
            'PROPOSAL_READBACK': ('pull_view', lambda n: {**original_view(n), 'user': {'login': 'aieh-bot-planner'}}),
        }
        for code, (name, damage) in damages.items():
            with self.subTest(code=code):
                self.gitea = fg.FakeGitea(self.repository)
                original_create, original_files, original_view = (self.gitea.create_file, self.gitea.files,
                                                                   self.gitea.pull_view)
                setattr(self.gitea, name, damage)
                error = self.refused(code, refusal=False)
                self.assertIn('written before it, not undone', error.detail)
                self.assertTrue(all('reviews' not in r['path'] for r in self.gitea.requests))
                self.assertEqual(self.gitea.merge_count(), 0)

    def test_a_refused_write_stops_and_says_what_was_written(self):
        fake = self.gitea

        def refuse_pull(port, path, *, method='GET', body=None, headers=None, timeout=5.0):
            if method == 'POST' and path.endswith('/pulls'):
                return fake.reply(422, {'message': 'refused by the fake'})
            return fake(port, path, method=method, body=body, headers=headers, timeout=timeout)

        error = self.refused('PROPOSAL_FAILED', refusal=False, http=refuse_pull)
        self.assertIn('answered 422 (refused by the fake)', error.detail)
        self.assertIn(f'the branch work/{su.OPERATION} with {MANIFEST}', error.detail)
        self.assertEqual(fake.pulls, {})

    def test_bot_tokens_only(self):
        planner = R.ROLES['planner']['user']
        cases = {
            'CREDENTIAL_MISSING': bot_entries(**{R.target('builder'): None}),
            'CREDENTIAL_REFUSED': bot_entries(**{R.target('reviewer'): (AR.OWNER, fg.PASSWORD)}),
            'BOT_IDENTITY_INVALID': bot_entries(**{R.target('builder'): (BUILDER, fg.BOT_TOKENS[planner])}),
        }
        for code, entries in cases.items():
            with self.subTest(code=code):
                self.gitea = fg.FakeGitea(self.repository)
                self.main_before = self.gitea.branches['main']
                self.bots = fg.FixtureProvider({k: v for k, v in entries.items() if v is not None})
                error = self.refused(code)
                self.assertNothingWritten()
                self.assertNotIn(fg.PASSWORD, error.detail)
                self.assertLessEqual(set(self.bots.reads), {R.target('builder'), R.target('reviewer')})
        self.bots = fg.FixtureProvider(bot_entries(**{R.target('builder'): (BUILDER, 'a-password-not-a-token')}))
        self.refused('CREDENTIAL_REFUSED')
        self.assertEqual(self.provider.reads, [])

    def test_refusals_before_anything_is_read(self):
        other = AR.FIXTURE_REPOSITORY if self.repository == AR.AUTHORIZATION_REPOSITORY else AR.AUTHORIZATION_REPOSITORY
        for repository in (other, 'someone/else'):
            with self.subTest(repository=repository):
                self.refused('REPOSITORY_NOT_ADMITTED', repository=repository)
        for blob in (b'not json', b'[]', su.manifest(operation='Op-1'), su.manifest().replace(b'expiresAt', b'x'),
                     su.manifest(target='two\nlines'), 'text'):
            with self.subTest(blob=blob):
                self.refused('MANIFEST_INVALID', blob)
        self.assertEqual((self.bots.reads, self.gitea.requests), ([], []))
        with self.assertRaises(ValueError):
            self.propose(policies={})

    def test_the_session_sends_only_its_routes(self):
        session = PR.BotSession(self.pctx(), 'builder', fg.BOT_TOKENS[BUILDER])
        repo = f'/repos/{self.repository}'
        for method, path in (('POST', f'{repo}/pulls/1/merge'), ('GET', '/user'), ('DELETE', '/token'),
                             ('GET', f'/users/{AR.OWNER}/tokens'), ('POST', f'{repo}/contents/README.md'),
                             ('PATCH', f'{repo}/pulls/1'), ('GET', f'{repo}/pulls?state=all&page=1&limit=50'),
                             ('POST', '/user/repos'), ('GET', f'{repo}/branch_protections')):
            with self.subTest(method=method, path=path), self.assertRaises(ValueError):
                session.call(method, path)
        self.assertEqual(self.gitea.requests, [])
        # a separate allowlist: the recorder's (aieh-owner's reads and its one merge) gained none of these routes
        for path in (f'{repo}/contents/{MANIFEST}', f'{repo}/pulls', f'{repo}/pulls/1/reviews',
                     f'{repo}/pulls?state=open&page=1&limit=50'):
            self.assertFalse(any(p.match(path) for p in AR._READS) or AR._MERGE.match(path), path)
        self.assertFalse(any('merge' in p.pattern for _m, p in PR.BOT_ROUTES))
        session.close()
        with self.assertRaises(ValueError):
            session.call('GET', '/token')

    def test_the_command_line(self):
        said = self.dir / 'manifest.json'
        said.write_bytes(su.manifest())

        @contextlib.contextmanager
        def context(port, guard):
            self.assertIsNone(port)
            yield self.pctx(provider=AR.contract.WatchedProvider(self.bots, guard))

        # the default repository is the authorization repository
        argv = ['propose', str(said)] + ([] if self.repository == AR.AUTHORIZATION_REPOSITORY
                                         else ['--repository', self.repository])
        out, err = io.StringIO(), io.StringIO()
        code = PR.main(argv, out=out, err=err, context=context)
        self.assertEqual((code, err.getvalue()), (0, ''))
        self.assertEqual(json.loads(out.getvalue())['operation'], su.OPERATION)
        out, err = io.StringIO(), io.StringIO()
        self.assertEqual(PR.main(argv, out=out, err=err, context=context), 2)
        self.assertIn('OPERATION_NOT_NEW', err.getvalue())
        out, err = io.StringIO(), io.StringIO()
        self.assertEqual(PR.main(['propose', str(self.dir / 'absent.json')], out=out, err=err, context=context), 2)
        for token in fg.BOT_TOKENS.values():
            self.assertNotIn(token, out.getvalue() + err.getvalue())
        self.assertEqual(self.gitea.merge_count(), 0)

    def test_the_command_line_admits_the_authorization_repository_alone(self):
        """managed_context with the managed root, its host record and the platform provider stood in for."""
        said = self.dir / 'manifest.json'
        said.write_bytes(su.manifest())
        with mock.patch.object(AR.host.paths, 'resolve', return_value=mock.Mock(name='resolution')), \
                mock.patch.object(AR.host, 'layout', return_value='layout'), \
                mock.patch.object(AR.host, 'read_host_record', return_value={'port': 3456}), \
                mock.patch.object(AR.host, 'credential_provider', return_value=self.bots):
            with PR.managed_context() as ctx:
                self.assertEqual((ctx.port, list(ctx.policies), ctx.http), (3456, [AR.AUTHORIZATION_REPOSITORY], None))
                self.assertIsInstance(ctx.provider, fg.FixtureProvider)
            out, err = io.StringIO(), io.StringIO()
            code = PR.main(['propose', str(said), '--repository', AR.FIXTURE_REPOSITORY], out=out, err=err)
        self.assertEqual((code, out.getvalue()), (2, ''))
        self.assertIn('REPOSITORY_NOT_ADMITTED', err.getvalue())
        self.assertEqual(self.bots.reads, [])


class ProposalOnTheLedger(Proposal):
    """Every case above on the authorization repository, admitted as the command line admits it."""
    repository = AR.AUTHORIZATION_REPOSITORY


if __name__ == '__main__':
    unittest.main()
