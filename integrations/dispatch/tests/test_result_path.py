"""Tests for the result path (plan leaf E-05.4: ``result_path.py``), offline.

Run from the repository root, under the tools interpreter (Dulwich is required):

    <tools python> -I -B -m unittest discover -s integrations/dispatch/tests -p test_result_path.py -v

E-05.4's proof, clause by clause, against the Gitea fakes: the owner suite's fake Gitea API (fake_gitea.FakeGitea,
called in memory) and the demo repository's smart-HTTP side (Dulwich's own server under wsgiref on 127.0.0.1, its
references mirrored into the fake's view), with a real verified result (``attempt_run.intake_result`` over a
repository and bundle written here with Dulwich):

* from a reserved attempt's verified result, the dispatcher, as the stage's bot, pushes ``work/<attempt>`` and opens
  one draft pull request naming the repository, base, exact SHA and task (``FirstRun``);
* a retry is preceded by reconciliation with Gitea's actual state and creates no second branch or pull request: the
  same attempt's branch at the exact SHA and its pull request are reused (nothing written); a branch at another SHA
  is RESULT_BRANCH_CONFLICT; an earlier attempt's open pull request is RESULT_EARLIER_PR_OPEN; a moved base is
  RESULT_BASE_MOVED; an end record is ATTEMPT_ENDED; a lost answer at the push or at the pull request leaves the
  journal ``unknown``, and the next run settles it by reading (``Retry``);
* no bot can merge it: the bot session has no merge route (refused before anything is sent), the fake refuses a
  bot's merge, and the demo rules' merge allowlist is ``[aieh-owner]`` (``NoMerge``);
* the outbound search: dispatch is refused without a not-found report naming the bundle and every text; a token
  planted in the test output, in a file of the result, or in the report stops the path before any write
  (``Search``);
* the diff is computed by host code from the verified objects, with no process launched, rendered as bounded data
  with control characters removed; the test output too; a result resumed from its intake receipt shows only the
  digests of the agent's text (``Report``); the journal and the hook (``Journal``).

Synthetic tokens only, built at run time; every repository and file in a throwaway directory.
"""
from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer

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


te = _load('test_attempt_end', HERE / 'test_attempt_end.py')
tr = _load('test_attempt_run', HERE / 'test_attempt_run.py')
fg = _load('fake_gitea', REPO / 'integrations' / 'owner' / 'tests' / 'fake_gitea.py')
di, AE, store_mod, NT = te.di, te.AE, te.store_mod, te.NT
AR = tr.AR
RP = _load('result_path', HERE.parent / 'result_path.py')
AT, roles = RP.AT, RP.roles
ra = di.planning.repository_access

DEMO = roles.DEMO_REPOSITORY
BUILDER = roles.ROLES['builder']['user']
PORT = 13300
OUTPUT = 'test_slugify (tests.test_slugify.S.test_it) ... ok\n\n' + '-' * 70 + '\nRan 2 tests in 0.001s\n\nOK\n'
SLUGIFY = 'def slugify(text):\n    return "-".join(text.lower().split())\n'


class Quiet(WSGIRequestHandler):
    def log_message(self, *_args):
        pass


class DemoRemote:
    """The demo repository's smart-HTTP side: Dulwich's server on 127.0.0.1 serving a bare repository holding the
    base history, ``main`` at the base. Gitea's rules as the demo declares them: the builder bot's token pushes
    ``work/*`` and nothing pushes ``main``; anything else is 401. ``drop`` ('before', 'after') loses the answer to
    the next receive-pack POST, before or after the update landed."""

    def __init__(self, tmp: Path, source: Path, main: str):
        d = ra.dulwich_modules()
        from dulwich import errors, server, web
        from dulwich.config import StackedConfig
        self.path = tmp / 'remote.git'
        self.path.mkdir()
        self.repo = d.repo.Repo.init_bare(str(self.path), config=StackedConfig([]), default_branch=b'main')
        r = self.repo
        r.get_config_stack = lambda: StackedConfig([r.get_config()])
        copy_objects(source, r)
        r.refs[b'refs/heads/main'] = main.encode('ascii')

        class Protect:
            def execute(self, ref, old, new):
                if not ref.startswith(b'refs/heads/work/'):
                    raise errors.HookError('protected branch')
                return b'', b''

        r.hooks = {'update': Protect()}
        app = web.make_wsgi_chain(server.DictBackend({f'/{DEMO}.git': r}))
        writer = 'token ' + fg.BOT_TOKENS[BUILDER]
        self.drop, self.posts, self.headers = None, 0, []

        def authorizing(environ, start_response):
            header = environ.get('HTTP_AUTHORIZATION')
            self.headers.append(header)
            if header != writer:
                start_response('401 Unauthorized', [('WWW-Authenticate', 'Basic realm="gitea"')])
                return [b'authentication required\n']
            if environ['REQUEST_METHOD'] == 'POST' and environ['PATH_INFO'].endswith('git-receive-pack'):
                self.posts += 1
                drop, self.drop = self.drop, None
                if drop == 'before':
                    start_response('502 Bad Gateway', [('Content-Type', 'text/plain')])
                    return [b'lost\n']
                if drop == 'after':
                    for _ in app(environ, lambda *a, **k: None):
                        pass
                    start_response('502 Bad Gateway', [('Content-Type', 'text/plain')])
                    return [b'lost after the update\n']
            return app(environ, start_response)

        self.httpd = WSGIServer(('127.0.0.1', 0), Quiet)
        self.httpd.set_app(authorizing)
        self.url = f'http://127.0.0.1:{self.httpd.server_address[1]}/{DEMO}.git'
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
        self.thread.start()

    def heads(self) -> dict:
        return {k.decode()[len('refs/heads/'):]: v.decode() for k, v in self.repo.get_refs().items()
                if k.startswith(b'refs/heads/')}

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()
        self.repo.close()


class DemoGitea(fg.FakeGitea):
    """The fake Gitea API over the demo repository: its branches are the smart-HTTP side's references, read at each
    request (a push is seen at once)."""

    def __init__(self, remote: DemoRemote):
        super().__init__()                # the demo is not a repository the protection auditor reads
        self.repository = DEMO
        self.repo['full_name'] = DEMO
        self.remote = remote
        self.branches = {}
        self.sync()

    def sync(self):
        for name, oid in self.remote.heads().items():
            self.branches[name] = oid
            self.commits.setdefault(oid, {'parents': [], 'tree': {}, 'message': ''})

    def _handle(self, method, path, headers, body):
        self.sync()
        return super()._handle(method, path, headers, body)

    def writes(self):
        return [r for r in self.requests if r['method'] != 'GET']


def copy_objects(source: Path, target) -> None:
    d = ra.dulwich_modules()
    src = d.repo.Repo(str(source))
    try:
        for oid in src.object_store:
            target.object_store.add_object(src.object_store[oid])
    finally:
        src.close()


class Fixture(te.EndFixture):
    """A confirmed native attempt, its turn confirmed, a verified result reserved by the hook, the demo repository
    on the fakes."""

    def setUp(self):
        super().setUp()
        self.scratch = Path(tempfile.mkdtemp(prefix='aieh-result-path-'))
        self.addCleanup(shutil.rmtree, self.scratch, True)
        patcher = mock.patch.dict(RP.ADMITTED_REPOSITORIES, {'demo-app': DEMO})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.attempt = self.dispatch_native()
        self.key = self.attempt.operation_key
        self.attempt_id = store_mod.attempt_id_for(self.key)
        self.server.set(self.attempt.conversation_id, status='finished')
        self.resolved = di.stored_inputs(self.store, self.key, state='confirmed')
        self.source = self.scratch / 'demo'
        commits = tr.make_repository(self.source, tr.demo_trees(self.resolved.work_id,
                                                                AR._design(self.resolved)['change']))
        self.base = AR.read_base(self.source, repository=self.resolved.repository, design_commit=commits['C2'])
        self.base = dataclasses.replace(self.base, design_commit=AR._design(self.resolved)['commit'])
        tr.confirm_turn(self.store, self.key, self.base)
        self.remote = DemoRemote(self.scratch, self.source, self.base.commit)
        self.addCleanup(self.remote.close)
        self.gitea = DemoGitea(self.remote)
        self.bot_provider = fg.FixtureProvider({roles.target('builder'): (BUILDER, fg.BOT_TOKENS[BUILDER])})
        self.native = NT.NativeToken(te.TOKEN)
        self.target = RP.GiteaTarget(repository_id=self.resolved.repository, full_name=DEMO, port=PORT,
                                     git_url=self.remote.url, http=self.gitea)

    # -- a verified result

    def verified(self, edits=None, output=OUTPUT, status='0', excluded=(), name='verify', resumed=False):
        """A result verified by attempt_run's intake: the base tree with EDITS ({path: bytes}), committed as the
        dispatcher specifies, in a bare repository and a complete bundle written with Dulwich."""
        d = ra.dulwich_modules()
        from dulwich.config import StackedConfig
        files = {p: (m, data) for p, m, data in self.base.files}
        for path, data in (edits if edits is not None else {'aieh_d1_demo/slugify.py': SLUGIFY.encode()}).items():
            files[path] = (AR.FILE_MODE, data)
        path = self.scratch / f'{name}.git'
        path.mkdir()
        repo = d.repo.Repo.init_bare(str(path), config=StackedConfig([]), default_branch=b'main')
        try:
            copy_objects(self.source, repo)
            tree = tr._tree(d, repo, files).decode('ascii')
            message = AR.commit_message(self.resolved, self.base, self.attempt_id)
            when = AR.attempt_time(self.store, self.key)
            raw = AR.expected_commit(tree, self.base.commit, message, when)
            commit = d.objects.ShaFile.from_raw_string(1, raw)
            repo.object_store.add_object(commit)
            commit_id = commit.id.decode('ascii')
            self.assertEqual(commit_id, AR.object_id('commit', raw))
            repo.refs[AR.result_ref(self.attempt_id).encode()] = commit.id
        finally:
            repo.close()
        staged = self.scratch / f'{name}-{AR.result_name(self.attempt_id)}'
        header = ra.open_repository(path, config='none', work_tree=False).write_bundle(
            [AR.result_ref(self.attempt_id)], staged)
        data = staged.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        raw_output = output.encode('utf-8')
        listed = json.dumps(list(excluded), sort_keys=True).encode('utf-8')
        printed = {'base': self.base.commit, 'tree': tree, 'commit': commit_id,
                   'bundle': {'sha256': sha, 'size': len(data)},
                   'tests': {'status': status, 'output': AR._data_text(output),
                             'output_digest': {'sha256': hashlib.sha256(raw_output).hexdigest(),
                                               'bytes': len(raw_output)},
                             'command': AR.TEST_COMMAND, 'label': AR.TEST_LABEL},
                   'excluded': list(excluded),
                   'excluded_digest': {'count': len(excluded), 'sha256': hashlib.sha256(listed).hexdigest(),
                                       'shown': len(excluded), 'shownSha256': hashlib.sha256(listed).hexdigest()},
                   'delivered': {'name': AR.result_name(self.attempt_id), 'sha256': sha, 'size': len(data)}}
        pulled = {'result': 'pulled', 'staged': {'path': str(staged), 'bytes': len(data), 'sha256': sha},
                  'bundle': {'verified': True, 'verify_repo': str(path), 'header': header}}
        result = AR.intake_result(self.store, self.key, base=self.base, printed=printed, pulled=pulled,
                                  message=message, when=when)
        if resumed:   # as attempt_run._resumed_result makes it from the intake receipt: digests only
            record = result.to_json()
            result = dataclasses.replace(result, tests=dict(record['tests'], output=None,
                                                            output_digest=record['tests']['output']),
                                         excluded=(), resumed=True)
        return result

    def reserved(self, **kwargs):
        verified = self.verified(**kwargs)
        RP.result_hook(self.store, self.key, actor='e-05.4-test')(verified.to_json(), verified)
        return verified

    def publish(self, verified, **kwargs):
        return RP.publish_result(self.store, self.key, verified=verified, native=kwargs.pop('native', self.native),
                                 provider=self.bot_provider, target=kwargs.pop('target', self.target),
                                 actor='e-05.4-test', **kwargs)

    def refused(self, code, verified, **kwargs):
        with self.assertRaises(di.DispatchRefused) as caught:
            self.publish(verified, **kwargs)
        self.assertEqual(caught.exception.code, code, caught.exception.detail)
        self.assertIn(code, di.REFUSALS)
        return caught.exception

    def journal(self):
        return self.store.get(RP.RESULT_KEY.format(attempt_id=self.attempt_id))

    def states(self):
        return [e.to_state for e in self.store.events(RP.RESULT_KEY.format(attempt_id=self.attempt_id))]

    def branch(self):
        return f'work/{self.attempt_id}'

    def assertOneBranchAndPull(self, verified):
        self.assertEqual(self.remote.heads().get(self.branch()), verified.commit)
        self.assertEqual([n for n, pr in self.gitea.pulls.items() if pr['head_ref'] == self.branch()], [1])
        self.assertEqual(len(self.gitea.pulls), 1)


class FirstRun(Fixture):
    def test_the_bot_pushes_the_branch_and_opens_one_draft_pull_request_naming_what_e_05_4_requires(self):
        verified = self.reserved()
        self.assertEqual(self.journal().state, 'reserved')
        outcome = self.publish(verified)
        self.assertEqual((outcome.outcome, outcome.pushed, outcome.opened), ('confirmed', True, True))
        self.assertOneBranchAndPull(verified)
        self.assertEqual(self.remote.posts, 1)
        pr = self.gitea.pull_view(1)
        self.assertEqual((pr['state'], pr['merged'], pr['draft'], pr['mergeable']), ('open', False, True, False))
        self.assertEqual(pr['user']['login'], BUILDER)
        self.assertEqual((pr['base']['ref'], pr['head']['ref'], pr['head']['sha']),
                         ('main', self.branch(), verified.commit))
        self.assertTrue(pr['title'].startswith('WIP: ' + self.resolved.work_id + ': '))
        for named in (DEMO, self.resolved.repository, self.base.commit, verified.commit, self.resolved.work_id,
                      self.attempt_id, self.resolved.outcome_ref, self.resolved.design_revision,
                      'not independent CI', 'Outcome: **PASSED**', 'Ran 2 tests'):
            self.assertIn(named, pr['body'])
        # every Gitea request was the builder's, none merged, none outside the bot session's routes
        self.assertEqual({r['doer'] for r in self.gitea.requests}, {BUILDER})
        self.assertEqual([(r['method'], r['path']) for r in self.gitea.writes()],
                         [('POST', f'/api/v1/repos/{DEMO}/pulls')])
        self.assertFalse(any('/merge' in r['path'] for r in self.gitea.requests))
        self.assertEqual(set(self.remote.headers), {'token ' + fg.BOT_TOKENS[BUILDER]})
        self.assertEqual(self.states(), ['reserved', 'dispatched', 'confirmed'])

    def test_the_receipt_holds_the_lineage_in_the_reader_s_grammars_and_the_commit_its_trailers(self):
        verified = self.reserved()
        outcome = self.publish(verified)
        got = RP.receipt(self.store, self.attempt_id)
        self.assertEqual(outcome.receipt, got)
        self.assertEqual(got['format'], RP.RECEIPT_FORMAT)
        expected = {'workRef': f'backlog:{self.resolved.work_id}', 'outcomeRef': self.resolved.outcome_ref,
                    'executionRef': f'openhands:conversation/{verified.conversation_id}',
                    'designRevision': self.resolved.design_revision,
                    'baseRef': f'git:{self.resolved.repository}@{self.base.commit}',
                    'resultRef': f'git:{self.resolved.repository}@{verified.commit}'}
        for name, text in expected.items():
            self.assertEqual(got[name], text)
            if name != 'designRevision':     # the store's design revision; the others the lineage reader's kinds
                self.assertEqual(di.lineage.parse(text).text, text)
        self.assertEqual([type(di.lineage.parse(got[n])).__name__ for n in ('workRef', 'outcomeRef', 'executionRef',
                                                                            'resultRef')],
                         ['WorkRef', 'ObjectiveRef', 'AttemptRef', 'CommitRef'])
        self.assertTrue(store_mod.valid_design_revision(got['designRevision']))
        self.assertEqual(got['pullRequest']['number'], 1)
        self.assertEqual(got['pullRequest']['url'], f'http://127.0.0.1:{PORT}/{DEMO}/pulls/1')
        self.assertEqual((got['branch'], got['commit'], got['bundle']['sha256']),
                         (self.branch(), verified.commit, verified.bundle_sha256))
        self.assertEqual(got['trailers'], {'Task': self.resolved.work_id, 'Attempt': self.attempt_id,
                                           'Outcome': self.resolved.outcome_ref,
                                           'Design': self.resolved.design_revision})
        self.assertEqual((got['search']['before']['verdict'], got['search']['after']['verdict']),
                         ('not-found', 'not-found'))
        self.assertTrue(got['search']['before']['controlsValid'])
        self.assertNotIn(te.TOKEN, json.dumps(got))
        self.assertNotIn('Ran 2 tests', json.dumps(got))          # S7: the store holds digests, not agent text

    def test_a_failing_test_run_is_marked_failed_and_the_path_proceeds(self):
        verified = self.reserved(output='FAILED (failures=1)\n', status='1')
        self.publish(verified)
        body = self.gitea.pull_view(1)['body']
        self.assertIn('Outcome: **FAILED (exit 1)**', body)
        self.assertIn('FAILED (failures=1)', body)

    def test_a_confirmed_journal_is_the_end_of_the_path_and_the_end_is_refused(self):
        verified = self.reserved()
        self.publish(verified)
        with self.assertRaises(di.DispatchRefused) as caught:
            self.end(self.attempt, trigger=AE.ATTEMPT_STOPPED, records=[te.record('model-stop')])
        self.assertEqual(caught.exception.code, 'ATTEMPT_RESULT_HANDED_ON')

    def test_the_report_is_written_after_the_search_and_never_overwritten(self):
        verified = self.reserved()
        where = self.scratch / 'report'
        outcome = self.publish(verified, report_dir=where)
        json_text, md = RP.report_texts(outcome.report)
        self.assertEqual((where / 'report.json').read_text(encoding='utf-8'), json_text)
        self.assertEqual((where / 'report.md').read_text(encoding='utf-8'), md)
        self.assertEqual(outcome.receipt['report']['markdownSha256'], hashlib.sha256(md.encode()).hexdigest())
        with self.assertRaises(ValueError):
            RP.write_report(where, json_text, md + 'changed')


class Retry(Fixture):
    def test_the_same_attempt_again_writes_nothing(self):
        verified = self.reserved()
        self.publish(verified)
        requests, posts = len(self.gitea.requests), self.remote.posts
        again = self.publish(verified)
        self.assertEqual(again.outcome, 'already-confirmed')
        self.assertEqual((len(self.gitea.requests), self.remote.posts), (requests, posts))
        self.assertOneBranchAndPull(verified)

    def test_a_branch_and_pull_request_already_there_are_reused_with_no_write(self):
        verified = self.reserved()
        real, calls = RP.pull_of, []

        def losing(*args, **kwargs):      # the read-back's answer is lost: both are on Gitea, the journal unknown
            calls.append(1)
            if len(calls) == 2:
                raise di.DispatchRefused('RESULT_GITEA_UNAVAILABLE', 'lost')
            return real(*args, **kwargs)
        with mock.patch.object(RP, 'pull_of', losing):
            refusal = self.refused('RESULT_WRITE_UNSETTLED', verified)
        self.assertEqual((refusal.context['step'], self.journal().state), ('readback', 'unknown'))
        posts, writes = self.remote.posts, len(self.gitea.writes())
        outcome = self.publish(verified)
        self.assertEqual((outcome.outcome, outcome.pushed, outcome.opened), ('confirmed', False, False))
        self.assertEqual((self.remote.posts, len(self.gitea.writes())), (posts, writes))
        self.assertOneBranchAndPull(verified)

    def test_a_branch_at_another_sha_is_refused(self):
        verified = self.reserved()
        other = self.verified(edits={'aieh_d1_demo/slugify.py': b'other\n'}, name='other')
        copy_objects(Path(other.verify_repo), self.remote.repo)
        self.remote.repo.refs[f'refs/heads/{self.branch()}'.encode()] = other.commit.encode()
        self.refused('RESULT_BRANCH_CONFLICT', verified)
        self.assertEqual((self.remote.posts, self.gitea.writes(), self.journal().state), (0, [], 'reserved'))
        self.assertEqual(self.remote.heads()[self.branch()], other.commit)

    def test_an_earlier_attempt_s_open_pull_request_is_refused(self):
        # attempt 1 is interrupted and ended; attempt 2 is admitted; attempt 1's pull request is open on Gitea
        first = self.attempt_id
        self.server.set(self.attempt.conversation_id, status='error',
                        events=[te.message_event('working', 'user'), te.SURFACED['repeated-529'][0]])
        self.assertEqual(self.end(self.attempt)['classification'], AE.INTERRUPTION)
        self.attempt = self.dispatch_native()
        self.key, self.attempt_id = self.attempt.operation_key, store_mod.attempt_id_for(self.attempt.operation_key)
        self.server.set(self.attempt.conversation_id, status='finished')
        self.resolved = di.stored_inputs(self.store, self.key, state='confirmed')
        tr.confirm_turn(self.store, self.key, self.base)
        self.gitea.propose({'x.txt': b'x\n'}, author=BUILDER, branch=f'work/{first}', title='WIP: earlier')
        verified = self.reserved()
        refusal = self.refused('RESULT_EARLIER_PR_OPEN', verified)
        self.assertEqual(refusal.context['earlier'], [{'number': 1, 'attemptId': first}])
        self.assertEqual((self.remote.posts, self.gitea.writes(), self.journal().state), (0, [], 'reserved'))
        # a pull request of a branch that is no attempt of the task is not the task's
        stranger = 'work/00000000-0000-4000-8000-000000000000'
        self.gitea.branches[stranger] = self.gitea.branches.pop(f'work/{first}')
        self.gitea.pulls[1]['head_ref'] = stranger
        self.assertEqual(self.publish(verified).outcome, 'confirmed')

    def test_a_moved_base_is_refused(self):
        verified = self.reserved()
        d = ra.dulwich_modules()
        moved = d.objects.Commit()
        moved.tree = d.objects.ShaFile.from_raw_string(1, self.remote.repo.object_store[
            self.base.commit.encode()].as_raw_string()).tree
        moved.parents = [self.base.commit.encode()]
        moved.author = moved.committer = b'Owner <owner@localhost.invalid>'
        moved.author_time = moved.commit_time = 1763300000
        moved.author_timezone = moved.commit_timezone = 0
        moved.message = b'moved\n'
        self.remote.repo.object_store.add_object(moved)
        self.remote.repo.refs[b'refs/heads/main'] = moved.id
        refusal = self.refused('RESULT_BASE_MOVED', verified)
        self.assertEqual(refusal.context['base_head'], moved.id.decode())
        self.assertEqual((self.remote.posts, self.gitea.writes(), self.journal().state), (0, [], 'reserved'))

    def test_an_attempt_with_an_end_record_is_refused_with_no_call(self):
        verified = self.reserved()
        self.end(self.attempt, trigger=AE.ATTEMPT_STOPPED, records=[te.record('model-stop')])
        self.refused('ATTEMPT_ENDED', verified)
        self.assertEqual((self.gitea.requests, self.remote.posts), ([], 0))

    def test_a_lost_answer_at_the_push_is_settled_by_reading(self):
        for landed in (True, False):
            with self.subTest(landed=landed):
                case = Retry('test_a_lost_answer_at_the_push_is_settled_by_reading')
                case.setUp()
                self.addCleanup(case.doCleanups)
                verified = case.reserved()
                case.remote.drop = 'after' if landed else 'before'
                refusal = case.refused('RESULT_WRITE_UNSETTLED', verified)
                self.assertEqual(refusal.context['step'], 'push')
                self.assertEqual(case.journal().state, 'unknown')
                self.assertEqual(case.remote.heads().get(case.branch()), verified.commit if landed else None)
                self.assertEqual(case.gitea.writes(), [])
                outcome = case.publish(verified)
                self.assertEqual((outcome.outcome, outcome.pushed, outcome.opened), ('confirmed', not landed, True))
                self.assertEqual(case.remote.posts, 1 if landed else 2)
                case.assertOneBranchAndPull(verified)
                self.assertEqual(case.states(), ['reserved', 'dispatched', 'unknown', 'confirmed'])

    def test_a_lost_answer_at_the_pull_request_is_settled_by_reading(self):
        verified = self.reserved()
        self.gitea.drop_after.add(('POST', '/pulls'))
        refusal = self.refused('RESULT_WRITE_UNSETTLED', verified)
        self.assertEqual(refusal.context['step'], 'pull-request')
        self.assertEqual(self.journal().state, 'unknown')
        self.gitea.drop_after.clear()
        posts = len([r for r in self.gitea.writes() if r['path'].endswith('/pulls')])
        outcome = self.publish(verified)
        self.assertEqual((outcome.outcome, outcome.pushed, outcome.opened), ('confirmed', False, False))
        self.assertEqual(len([r for r in self.gitea.writes() if r['path'].endswith('/pulls')]), posts)
        self.assertOneBranchAndPull(verified)
        self.assertEqual(self.states(), ['reserved', 'dispatched', 'unknown', 'confirmed'])

    def test_a_pull_request_refused_by_gitea_leaves_the_journal_to_a_reading(self):
        verified = self.reserved()
        with mock.patch.object(self.gitea, 'open_pull', lambda doer, form: self.gitea.reply(500, {'message': 'x'})):
            refusal = self.refused('RESULT_WRITE_UNSETTLED', verified)
        self.assertEqual((refusal.context['step'], refusal.context['cause']), ('pull-request', 'HTTP 500'))
        self.assertEqual((self.journal().state, self.gitea.pulls), ('unknown', {}))
        outcome = self.publish(verified)            # settled by reading: the branch is there, the pull request not
        self.assertEqual((outcome.pushed, outcome.opened), (False, True))
        self.assertOneBranchAndPull(verified)

    def test_a_pull_request_that_is_not_the_one_opened_here_is_not_reused(self):
        verified = self.reserved()
        copy_objects(Path(verified.verify_repo), self.remote.repo)
        self.remote.repo.refs[f'refs/heads/{self.branch()}'.encode()] = verified.commit.encode()
        self.gitea.sync()
        self.gitea.open_pull(BUILDER, {'head': self.branch(), 'base': 'main', 'title': 'not the title'})
        self.refused('RESULT_PR_CONFLICT', verified)
        self.assertEqual((self.remote.posts, self.journal().state), (0, 'reserved'))

    def test_a_run_stopped_after_the_dispatch_is_settled_by_reading(self):
        verified = self.reserved()
        key = RP.RESULT_KEY.format(attempt_id=self.attempt_id)
        di._mark(self.store, key, 'reserved', 'dispatched', 'e-05.4-test', 'push', None)
        outcome = self.publish(verified)
        self.assertEqual(outcome.outcome, 'confirmed')
        self.assertEqual(self.states(), ['reserved', 'dispatched', 'unknown', 'confirmed'])
        self.assertOneBranchAndPull(verified)


class NoMerge(Fixture):
    def test_the_bot_session_has_no_merge_route_and_refuses_before_sending(self):
        verified = self.reserved()
        with AT.attempt_role_token(self.store, self.key, provider=self.bot_provider, port=PORT,
                                   http=self.gitea) as delivery:
            session = AT.ResultSession(delivery, repository=DEMO, port=PORT, http=self.gitea)
            sent = len(self.gitea.requests)
            for method, path in (('POST', f'/repos/{DEMO}/pulls/1/merge'), ('POST', f'/repos/{DEMO}/pulls/1/reviews'),
                                 ('POST', f'/repos/{DEMO}/contents/x.txt'), ('PATCH', f'/repos/{DEMO}/pulls/1'),
                                 ('DELETE', f'/repos/{DEMO}/branches/{self.branch()}'),
                                 ('GET', f'/repos/{DEMO}/pulls/1/merge'), ('GET', '/token'),
                                 ('POST', f'/repos/other/repo/pulls'), ('GET', f'/repos/{DEMO}/branches/other'),
                                 ('GET', f'/repos/{DEMO}/pulls?state=all&page=1&limit=50'),
                                 # review of B and C, NIT 1: a trailing newline (re's $ matched before it)
                                 ('GET', f'/repos/{DEMO}/branches/main\n'), ('POST', f'/repos/{DEMO}/pulls\n')):
                with self.subTest(method=method, path=path):
                    with self.assertRaises(di.DispatchRefused) as caught:
                        session.call(method, path, {'Do': 'merge'} if method == 'POST' else None)
                    self.assertEqual(caught.exception.code, 'BOT_ROUTE_REFUSED')
            self.assertEqual(len(self.gitea.requests), sent)
        with self.assertRaises(ValueError):       # the session ends with the attempt context
            session.call('GET', f'/repos/{DEMO}/branches/main')
        self.assertTrue(verified)

    def test_the_fake_refuses_a_bot_merge_and_the_demo_rules_allow_only_the_owner(self):
        verified = self.reserved()
        self.publish(verified)
        token = fg.BOT_TOKENS[BUILDER]
        status, _, _ = self.gitea(PORT, f'/api/v1/repos/{DEMO}/pulls/1/merge', method='POST',
                                  body=json.dumps({'Do': 'merge'}).encode(),
                                  headers={'Authorization': 'token ' + token})
        self.assertEqual(status, 405)
        self.assertEqual((self.gitea.merge_count(), self.gitea.pull_view(1)['merged']), (0, False))
        for rule in roles.demo_declaration()['rules']:
            self.assertEqual((rule['enable_merge_whitelist'], rule['merge_whitelist_usernames']),
                             (True, [roles.host.OWNER]))
            self.assertFalse(rule['enable_force_push'])

    def test_the_routes_are_exactly_the_declared_ones(self):
        routes = [(m, p.pattern) for m, p in AT.result_routes(DEMO)]
        self.assertEqual([m for m, _ in routes], ['GET', 'GET', 'GET', 'GET', 'POST'])
        self.assertFalse(any(word in p for _, p in routes for word in ('merge', 'reviews', 'contents', 'token')))
        with self.assertRaises(ValueError):
            AT.result_routes('../x')


class Search(Fixture):
    def assertNothingWritten(self):
        self.assertEqual((self.gitea.requests, self.remote.posts, self.journal().state), ([], 0, 'reserved'))

    def test_a_token_in_the_test_output_stops_the_path_before_any_write(self):
        verified = self.reserved(output=f'leaked {te.TOKEN}\n')
        refusal = self.refused('OUTBOUND_TOKEN_FOUND', verified)
        self.assertIn('test-output', refusal.context['where'])
        self.assertNothingWritten()

    def test_a_token_in_a_file_of_the_result_stops_the_path(self):
        verified = self.reserved(edits={'aieh_d1_demo/notes.txt': f'token={te.TOKEN}\n'.encode()})
        refusal = self.refused('OUTBOUND_TOKEN_FOUND', verified)
        self.assertIn(RP.BUNDLE_LABEL, refusal.context['where'])
        self.assertNothingWritten()

    def test_a_token_in_the_report_stops_the_path(self):
        verified = self.reserved()
        self.refused('OUTBOUND_TOKEN_FOUND', verified, observations={'note': te.TOKEN})
        self.assertNothingWritten()
        self.refused('OUTBOUND_TOKEN_FOUND', verified, extra_texts={'run-record': 'x ' + te.TOKEN})
        self.assertNothingWritten()

    def test_an_encoded_token_is_found_too(self):
        import base64
        verified = self.reserved(output=base64.b64encode(te.TOKEN.encode()).decode() + '\n')
        self.refused('OUTBOUND_TOKEN_FOUND', verified)
        self.assertNothingWritten()

    def test_another_token_or_none_is_refused(self):
        verified = self.reserved()
        self.refused('OUTBOUND_TOKEN_MISMATCH', verified, native=NT.NativeToken(te.NEW_TOKEN))
        self.refused('OUTBOUND_SEARCH_REQUIRED', verified, native=None)
        dropped = NT.NativeToken(te.TOKEN)
        dropped.drop()
        self.refused('OUTBOUND_SEARCH_REQUIRED', verified, native=dropped)
        self.assertNothingWritten()

    def test_dispatch_needs_a_not_found_report_naming_the_bundle_and_every_text(self):
        verified = self.reserved()
        texts = {'pr-body': 'the body'}
        report = RP.outbound_search(self.native, expected_fingerprint=self.native.fingerprint, texts=texts,
                                    bundle_path=verified.staged, bundle_sha256=verified.bundle_sha256)
        summary = RP.require_not_found(report, bundle_sha256=verified.bundle_sha256, texts=texts)
        self.assertEqual((summary['verdict'], summary['controlsValid']), ('not-found', True))
        self.assertEqual(summary['subject']['bundle']['sha256'], verified.bundle_sha256)
        cases = {
            'none': (None, 'OUTBOUND_SEARCH_REQUIRED'),
            'another bundle': (dict(report, subject={**report['subject'], 'bundle': {'sha256': 'f' * 64}}),
                               'OUTBOUND_SEARCH_REQUIRED'),
            'no bundle surface': (dict(report, surfaces=[s for s in report['surfaces']
                                                          if s['label'] != RP.BUNDLE_LABEL]),
                                  'OUTBOUND_SEARCH_REQUIRED'),
            'another text': (dict(report, subject={**report['subject'], 'texts': {'pr-body': 'f' * 64}}),
                             'OUTBOUND_SEARCH_REQUIRED'),
            'found': (dict(report, verdict='found'), 'OUTBOUND_TOKEN_FOUND'),
            'invalid': (dict(report, verdict='invalid'), 'OUTBOUND_SEARCH_NOT_PASSED'),
            'incomplete': (dict(report, verdict='incomplete'), 'OUTBOUND_SEARCH_NOT_PASSED'),
            'a control missed': (dict(report, bundle_control={'valid': False}), 'OUTBOUND_SEARCH_NOT_PASSED'),
        }
        for name, (given, code) in cases.items():
            with self.subTest(name):
                with self.assertRaises(di.DispatchRefused) as caught:
                    RP.require_not_found(given, bundle_sha256=verified.bundle_sha256, texts=texts)
                self.assertEqual(caught.exception.code, code)
        with self.assertRaises(di.DispatchRefused) as caught:   # the bundle on disk must be the verified one
            RP.outbound_search(self.native, expected_fingerprint=self.native.fingerprint, texts=texts,
                               bundle_path=verified.staged, bundle_sha256='0' * 64)
        self.assertEqual(caught.exception.code, 'RESULT_STAGED_UNVERIFIED')

    def test_the_path_never_dispatches_on_a_report_that_does_not_pass(self):
        verified = self.reserved()
        real = RP.outbound_search
        for verdict, code in (('invalid', 'OUTBOUND_SEARCH_NOT_PASSED'), ('incomplete', 'OUTBOUND_SEARCH_NOT_PASSED')):
            with self.subTest(verdict=verdict):
                with mock.patch.object(RP, 'outbound_search',
                                       lambda *a, **k: dict(real(*a, **k), verdict=verdict)):
                    self.refused(code, verified)
                self.assertNothingWritten()
        with mock.patch.object(RP, 'outbound_search', lambda *a, **k: dict(real(*a, **k), subject={})):
            self.refused('OUTBOUND_SEARCH_REQUIRED', verified)
        self.assertNothingWritten()


class Report(Fixture):
    def test_the_diff_is_computed_from_the_verified_objects_with_no_launch(self):
        verified = self.reserved(edits={'aieh_d1_demo/slugify.py': SLUGIFY.encode(),
                                        'README.md': b'# demo\n\nThe D1 demo, \x1b[31mred\x1b[0m.\n',
                                        'data.bin': b'\x00\x01\x02'})
        with mock.patch.object(subprocess, 'Popen', side_effect=AssertionError('a process was launched')):
            outcome = self.publish(verified)
        diff = outcome.report['json']['diff']
        self.assertEqual(diff['stats'], {'files': 3, 'added': 3, 'removed': 1})     # a binary file has no lines
        self.assertEqual([(f['path'], f['status']) for f in diff['files']],
                         [('README.md', 'modified'), ('aieh_d1_demo/slugify.py', 'added'), ('data.bin', 'added')])
        self.assertIn('+++ b/aieh_d1_demo/slugify.py\n@@ -0,0 +1,2 @@\n+def slugify(text):\n', diff['text'])
        self.assertIn('+The D1 demo, [31mred[0m.\n', diff['text'])      # the escape character removed
        self.assertNotIn('\x1b', diff['text'])
        self.assertIn('binary: 0 bytes', diff['text'])
        self.assertIn(diff['text'], outcome.report['markdown'])
        self.assertIn('Ran 2 tests', outcome.report['markdown'])
        self.assertEqual(outcome.report['json']['tests']['outcome'], 'PASSED')
        self.assertEqual(outcome.report['json']['pullRequest']['number'], 1)

    def test_control_characters_are_removed_from_the_test_output(self):
        verified = self.reserved(output='ok \x1b[0m\x07 done\n')
        outcome = self.publish(verified)
        self.assertEqual(outcome.report['json']['tests']['output'], 'ok [0m done\n')
        self.assertNotIn('\x07', self.gitea.pull_view(1)['body'])

    def test_a_backtick_run_in_the_output_cannot_close_its_fence(self):
        verified = self.reserved(output='```\n# heading\n````\n')
        self.publish(verified)
        body = self.gitea.pull_view(1)['body']
        self.assertIn('`````text\n```\n# heading\n````\n`````\n', body)

    def test_a_result_resumed_from_its_intake_receipt_shows_only_digests(self):
        excluded = [{'path': '.claude/settings.local.json', 'reason': 'forbidden-name'}]
        verified = self.reserved(excluded=excluded, resumed=True)
        outcome = self.publish(verified)
        body = self.gitea.pull_view(1)['body']
        digest = verified.tests['output_digest']
        self.assertIn('The output is not available in this run', body)
        self.assertIn(digest['sha256'], body)
        self.assertNotIn('Ran 2 tests', body)
        self.assertIn('Excluded: 1 path(s)', body)
        self.assertIn('The list is not available in this run', body)
        self.assertNotIn('.claude/settings.local.json', body)
        tests = outcome.report['json']['tests']
        self.assertEqual((tests['outputAvailable'], tests['output']), (False, None))
        self.assertEqual(outcome.report['json']['exclusions']['paths'], None)

    def test_the_excluded_paths_are_listed_when_they_are_held(self):
        excluded = [{'path': '.claude/settings.local.json', 'reason': 'forbidden-name'},
                    {'path': 'openspec/changes/add-slugify/tasks.md', 'reason': 'protected-dir'}]
        verified = self.reserved(excluded=excluded)
        outcome = self.publish(verified)
        body = self.gitea.pull_view(1)['body']
        self.assertIn('forbidden-name: .claude/settings.local.json\n', body)
        self.assertIn(AR.EXCLUSION_RULE, body)
        self.assertEqual(len(outcome.report['json']['exclusions']['paths']), 2)

    def test_the_observations_slot_is_carried_or_stated_empty(self):
        verified = self.reserved()
        outcome = self.publish(verified, observations={'interruption': 'none occurred'})
        self.assertEqual(outcome.report['json']['observations'], {'interruption': 'none occurred'})
        self.assertIn('"interruption": "none occurred"', outcome.report['markdown'])


class Journal(Fixture):
    def test_the_hook_is_repeat_safe_and_a_resumed_intake_reserves_the_same_journal(self):
        verified = self.reserved()
        hook = RP.result_hook(self.store, self.key, actor='e-05.4-test')
        self.assertEqual(hook(verified.to_json(), verified)['state'], 'reserved')
        resumed = dataclasses.replace(verified, tests=dict(verified.to_json()['tests'], output=None,
                                                           output_digest=verified.to_json()['tests']['output']),
                                      excluded=(), resumed=True)
        self.assertEqual(hook(resumed.to_json(), resumed)['state'], 'reserved')
        self.assertEqual(self.states(), ['reserved'])

    def test_another_result_for_the_attempt_is_a_conflict(self):
        self.reserved()
        other = self.verified(edits={'aieh_d1_demo/slugify.py': b'other\n'}, name='other')
        with self.assertRaises(di.DispatchRefused) as caught:
            RP.result_hook(self.store, self.key, actor='e-05.4-test')(other.to_json(), other)
        self.assertEqual(caught.exception.code, 'RESULT_JOURNAL_CONFLICT')
        self.refused('RESULT_JOURNAL_CONFLICT', other)

    def test_an_unreserved_result_or_a_foreign_record_is_refused(self):
        verified = self.verified()
        self.refused('RESULT_NOT_RESERVED', verified)
        with self.assertRaises(di.DispatchRefused) as caught:
            RP.result_hook(self.store, self.key, actor='e-05.4-test')({'other': 1}, verified)
        self.assertEqual(caught.exception.code, 'RESULT_NOT_RESERVED')
        self.assertEqual(self.gitea.requests, [])

    def test_a_result_that_changes_nothing_fails_its_journal_and_writes_nothing(self):
        verified = self.reserved(edits={})
        self.refused('RESULT_EMPTY_CHANGE', verified)
        self.assertEqual((self.journal().state, self.gitea.requests, self.remote.posts), ('failed', [], 0))
        self.refused('RESULT_JOURNAL_FAILED', verified)

    def test_only_the_admitted_repository_is_a_target(self):
        verified = self.reserved()
        for target in (dataclasses.replace(self.target, full_name='aieh-demo/other'),
                       dataclasses.replace(self.target, repository_id='other-app')):
            with self.subTest(target=target.full_name):
                self.refused('RESULT_REPOSITORY_NOT_ADMITTED', verified, target=target)
        with self.assertRaises(di.DispatchRefused) as caught:
            RP.gitea_target('other-app', PORT)
        self.assertEqual(caught.exception.code, 'RESULT_REPOSITORY_NOT_ADMITTED')
        made = RP.gitea_target('aieh-d1-demo', PORT)
        self.assertEqual((made.full_name, made.git_url), (DEMO, f'http://127.0.0.1:{PORT}/{DEMO}.git'))
        self.assertEqual(self.gitea.requests, [])


if __name__ == '__main__':
    unittest.main()
