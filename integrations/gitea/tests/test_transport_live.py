"""Live qualification of the repository module's transports against the running Gitea (plan leaf
F-10.6, decision 0014: SHIP-02, G13).

Opt-in: it runs only with AIEH_GITEA_TRANSPORT=1 (`task gitea:transport`), on Windows, under the
tools interpreter (Dulwich), while Gitea answers, every bot's Credential Manager entry exists and
the fixture repository (gitea_roles.py fixture) answers. Otherwise each class skips with its
reason, so the ordinary suites never read Credential Manager or write to Gitea.

It replays the git push matrix of `test_authorization_live.py` (`TestFixtureAllowed`,
`TestFixtureDenied`) through the module, as each bot: a bare clone over HTTP, a proposal-branch
push (`work/authz-<role>`: builder and planner allowed, reviewer and verifier refused), and, for
every bot, a fast-forward push, a force push and a deletion of the protected default branch, and
a push of a non-proposal branch, all refused. Each refusal must carry the module's stable code
(`PUSH_REFUSED` for HTTP 401 or 403, `PUSH_REJECTED` for a rejected update) and no module call may
launch a process. The default branch must not move. The only change left on the fixture is the
one the git suite also leaves: one new commit on builder's and planner's proposal branches.

**The protection auditor** (role ``protection-audit``: a ``read:repository`` token of a repository
administrator of the fixture, Owner decision OA-16). The other roles' pushes are the F-10.6 matrix,
unchanged. The auditor's five are not: each would change the fixture if Gitea wrongly accepted it, so each
is replaced by an update the repository module withholds before sending anything, after the receive-pack
advertisement, where Gitea's scope check refuses the token (HTTP 403, ``PUSH_REFUSED``): a commit unrelated
to main pushed to main without ``+`` (not a fast-forward), and the deletion of a branch the remote does not
have: its own proposal branch ``work/authz-protection-audit`` (for the proposal-branch push), an absent
branch forced (standing in for the force-push) and plain (for the delete by push), and the absent
``feature/authz-protection-audit`` (for the non-proposal branch). Their absence is read from the clone
first (one present: the test fails, not exercised). None is left unexercised. ``PUSH_REJECTED`` for the
auditor means Gitea served it the advertisement: a SECURITY FAILURE, as is a push that succeeds.

**The circuit breaker (Owner authorization OA-16 Act C; live_breaker.py).** Any unexpected acceptance, by
any role, trips this module's breaker: a push that must be refused succeeding, the auditor's
advertisement served, main moving (read after each role's pushes). From then on no push of any role is
sent: each checks the breaker immediately before it is sent, independently of ``subTest``; the role loop
stops, and ``tearDownModule`` fails the run and reports the push that tripped it and every push not sent.

Tokens are read from Credential Manager into memory by the same product code as the git suite
(`gitea_roles.read_token`) and handed to the module as `Credential`s; nothing prints, logs or
asserts on a token. AIEH_GITEA_TRANSPORT_REPORT, when set, names a JSON file that receives every
probe (role, action, expectation, outcome code, HTTP status; for an auditor push, what it would do if
Gitea wrongly accepted it), every push the circuit breaker withheld, and the breaker's state.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.parse
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

CATEGORY = 'e2e'

HERE = Path(__file__).resolve().parent


def _load(name, path):
    if (module := sys.modules.get(name)) is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = sys.modules[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


G = _load('aieh_gitea_host', HERE.parent / 'gitea_host.py')
R = _load('aieh_gitea_roles', HERE.parent / 'gitea_roles.py')
RA = _load('repository_access', HERE.parents[1] / 'repository' / 'repository_access.py')
LB = _load('aieh_gitea_live_breaker', HERE / 'live_breaker.py')
OPT_IN = os.environ.get('AIEH_GITEA_TRANSPORT') == '1'
REPORT = os.environ.get('AIEH_GITEA_TRANSPORT_REPORT')
RESULTS: list[dict] = []
REPO = f'/repos/{R.FIXTURE_ORG}/{R.FIXTURE_REPO}'
MAIN = f'refs/heads/{R.DEFAULT_BRANCH}'
PROPOSERS = ('builder', 'planner')
AUDITOR = 'protection-audit'
BREAKER = LB.Breaker(lambda row: RESULTS.append(row))
NOT_FAST_FORWARD = 'made non-mutating: the repository module refuses a push that is not a fast-forward before sending'
ABSENT_DELETE = 'made non-mutating: the repository module refuses deleting an absent reference before sending'
WITHHELD = ('non-fast-forward', 'remote ref does not exist', 'fetch first')
_LIVE: list = []


def live():
    """(context, None) when the live suite can run, else (None, the reason it skips)."""
    if not _LIVE:
        _LIVE.append(_probe_live())
    return _LIVE[0]


def _probe_live():
    if not OPT_IN:
        return None, 'live transport tests are opt-in: AIEH_GITEA_TRANSPORT=1 (task gitea:transport)'
    if os.name != 'nt':
        return None, 'the bot tokens are in Windows Credential Manager'
    try:
        RA.dulwich_modules()
    except RA.CannotRun as exc:
        return None, f'{exc.code}: run under the tools interpreter'
    try:
        res = G.paths.resolve()
        port = G.read_host_record(G.layout(res))['port']
    except (G.GiteaError, G.paths.PathsError) as exc:
        return None, f'Gitea is not installed here ({exc})'
    if not G.healthy(port):
        return None, 'Gitea is not running (task gitea:up)'
    store = G.credential_provider()
    tokens = {role: R.read_token(store, role) for role in R.ROLES}
    if missing := sorted(role for role, token in tokens.items() if token is None):
        return None, f'no Credential Manager entry for {missing} (gitea_roles.py provision)'
    return SimpleNamespace(port=port, tokens=tokens), None


def tearDownModule():
    BREAKER.close_run(RESULTS, REPORT)


def auditor_push_probes(orphan, absent) -> list:
    """The auditor's five pushes (``path`` the refspec), each withheld by the module before it sends anything."""
    return [
        LB.Probe(f'push its proposal branch, standing in: delete the absent work/authz-{AUDITOR} (module)', 'PUSH',
                 f':refs/heads/work/authz-{AUDITOR}', None, ABSENT_DELETE),
        LB.Probe('push to the protected branch: a commit unrelated to main, without force (module)', 'PUSH',
                 f'{orphan}:{MAIN}', None, NOT_FAST_FORWARD),
        LB.Probe('force-push, standing in: a forced deletion of an absent branch (module)', 'PUSH',
                 f'+:refs/heads/{absent}', None, ABSENT_DELETE),
        LB.Probe('delete by push: an absent branch (module)', 'PUSH', f':refs/heads/{absent}', None, ABSENT_DELETE),
        LB.Probe(f'push a non-proposal branch, standing in: delete the absent feature/authz-{AUDITOR} (module)',
                 'PUSH', f':refs/heads/feature/authz-{AUDITOR}', None, ABSENT_DELETE),
    ]


def rmtree(path):
    shutil.rmtree(path, onexc=lambda f, p, e: (os.chmod(p, 0o700), f(p)))


class launches:
    """Counts process launches inside the block (subprocess.Popen, wrapped, so a launch still
    happens and is attributed where it was made)."""

    def __enter__(self):
        self.patch = mock.patch.object(subprocess, 'Popen', wraps=subprocess.Popen)
        self.popen = self.patch.start()
        return self

    def __exit__(self, *exc):
        self.patch.stop()
        self.count = self.popen.call_count
        return False


class TransportLive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ctx, reason = live()
        if ctx is None:
            raise unittest.SkipTest(reason)
        cls.ctx = ctx
        status = R.Api(ctx.port, ctx.tokens['verifier']).call('GET', REPO)[0]
        if status != 200:
            raise unittest.SkipTest(f'the fixture repository answers {status} to the verifier: it is created by '
                                    'gitea_roles.py fixture, after task gitea:finalize-credentials')
        cls.url = f'http://{G.LOOPBACK}:{ctx.port}/{R.FIXTURE_ORG}/{R.FIXTURE_REPO}.git'
        cls.tmp = Path(tempfile.mkdtemp(prefix='aieh-transport-live-'))
        cls.addClassCleanup(rmtree, cls.tmp)
        cls.credentials = {role: RA.Credential(R.ROLES[role]['user'], token) for role, token in ctx.tokens.items()}
        cls.launched = 0

    def module(self, role, action, expect, call, *args, write=False, if_accepted=None):
        """CALL(*ARGS) through the module, recorded; returns (outcome code, result). A WRITE checks the
        circuit breaker first (not sent once it has tripped)."""
        if write:
            BREAKER.check(f'{role}: {action}')
        with launches() as seen:
            try:
                result, code, status = call(*args), 'ok', None
            except RA.RepositoryError as exc:
                result, code, status = exc, exc.code, exc.details.get('status')
        type(self).launched += seen.count
        row = {'role': role, 'action': action, 'expected': expect, 'outcome': code, 'status': status,
               'launches': seen.count, 'message': R.redact(getattr(result, 'message', ''))[-200:]}
        if if_accepted is not None:
            row['if accepted'] = if_accepted
        RESULTS.append(row)
        self.assertEqual(seen.count, 0, f'{role}: {action} launched a process')
        return code, result

    def denied_push(self, role, action, *args):
        """A push that must be refused: one that succeeds is a SECURITY FAILURE."""
        code, result = self.module(role, action, 'denied', *args, write=True)
        if code == 'ok':
            raise BREAKER.fail(f'{role}: {action} succeeded ({result})')
        return code, result

    def each_role(self, roles):
        """The roles in order, until the breaker trips: then the remaining roles' pushes are not sent."""
        roles = list(roles)
        for n, role in enumerate(roles):
            if BREAKER.tripped_by is not None:
                BREAKER.withhold(f'{r}: the remaining pushes of {self._testMethodName}' for r in roles[n:])
                return
            yield role

    def main_unchanged(self, before, during):
        now = self.branch_head(R.DEFAULT_BRANCH)
        if now != before:
            raise BREAKER.fail(f'{R.DEFAULT_BRANCH} moved during {during} ({before} -> {now})')

    def auditor_pushes(self, repo, refs, credential, run_id):
        absent = f'aieh-probe-absent-{os.urandom(4).hex()}'
        present = sorted({f'refs/heads/work/authz-{AUDITOR}', f'refs/heads/feature/authz-{AUDITOR}',
                          f'refs/heads/{absent}'} & set(refs))
        if present:
            self.fail(f'not exercised: {present} exist on the remote, so their deletion would not be withheld')
        orphan = self.new_commit(repo, AUDITOR, None, f'orphan {AUDITOR} {run_id}')
        failures = LB.sequence(BREAKER, auditor_push_probes(orphan, absent),
                               lambda probe: self.auditor_push(repo, probe, credential), self.failureException,
                               prefix=f'{AUDITOR}: ')
        if failures:
            self.fail('; '.join(failures))

    def auditor_push(self, repo, probe, credential):
        """One auditor push: PUSH_REFUSED with HTTP 403 (the receive-pack advertisement refused) passes. A
        SECURITY FAILURE: a push that succeeds, and PUSH_REJECTED (Gitea served the advertisement to the
        read:repository token; the module withheld the update, or Gitea rejected it). Any other answer fails."""
        code, result = self.module(AUDITOR, probe.action, 'PUSH_REFUSED (HTTP 403)', repo.push, self.url, probe.path,
                                   credential, write=True, if_accepted=probe.if_accepted)
        if code == 'ok':
            raise BREAKER.fail(f'{AUDITOR}: {probe.action} with the read:repository token succeeded ({result})')
        if code == 'PUSH_REJECTED':
            reason = result.details.get('reason')
            raise BREAKER.fail(
                f'{AUDITOR}: {probe.action}: Gitea served the receive-pack advertisement to the read:repository '
                'token (its scope did not refuse the push); ' + (
                    f'the repository module withheld the update ({reason}): no update was sent' if reason in WITHHELD
                    else f'the update was rejected after the advertisement ({reason})'))
        self.assertEqual((code, result.details.get('status')), ('PUSH_REFUSED', 403),
                         f'{AUDITOR}: {probe.action}: not refused by the scope')

    def branch_head(self, name):
        status, body = R.Api(self.ctx.port, self.ctx.tokens['verifier']).call(
            'GET', f'{REPO}/branches/{urllib.parse.quote(name, safe="")}')
        return body['commit']['id'] if status == 200 else None

    def new_commit(self, repo, role, parent, text):
        """A commit on PARENT adding <role>.txt, written into the clone with Dulwich's object API."""
        from dulwich import objects
        store = repo._dul.object_store
        tree = objects.Tree()
        for item in store[store[parent.encode()].tree].iteritems() if parent else ():
            tree.add(item.path, item.mode, item.sha)
        blob = objects.Blob.from_string(text.encode() + b'\n')
        tree.add(f'{role}.txt'.encode(), 0o100644, blob.id)
        made = objects.Commit()
        made.tree, made.parents = tree.id, [parent.encode()] if parent else []
        user = R.ROLES[role]['user']
        made.author = made.committer = f'{user} <{user}@{G.EMAIL_DOMAIN}>'.encode()
        made.author_time = made.commit_time = int(time.time())
        made.author_timezone = made.commit_timezone = 0
        made.message = text.encode() + b'\n'
        for obj in (blob, tree, made):
            store.add_object(obj)
        return made.id.decode()


class TestMatrix(TransportLive):
    def test_each_bot_through_the_module(self):
        main_before = self.branch_head(R.DEFAULT_BRANCH)
        self.assertIsNotNone(main_before)
        run_id = os.urandom(4).hex()
        for role in self.each_role(self.credentials):
            credential = self.credentials[role]
            with self.subTest(role=role):
                clone = self.tmp / f'{role}.git'
                code, refs = self.module(role, 'clone (module)', 'allowed', RA.clone, self.url, clone, credential)
                self.assertEqual(code, 'ok')
                self.assertEqual(refs.get(MAIN), main_before)
                token = RA.Credential(credential.username, credential.secret, scheme='token')
                code, listed = self.module(role, 'ls-remote with Authorization: token (module)', 'allowed',
                                           RA.ls_remote, self.url, token)
                self.assertEqual(code, 'ok')
                self.assertEqual(listed.get(MAIN), main_before)
                with RA.open_repository(clone, config='repository', work_tree=False, ceilings=[self.tmp]) as repo:
                    self.assertEqual(repo.commit('HEAD'), main_before)
                    if role == AUDITOR:
                        self.auditor_pushes(repo, refs, credential, run_id)
                        self.assertIsNone(self.branch_head(f'feature/authz-{role}'))
                        self.main_unchanged(main_before, f'the pushes of {role}')
                        continue
                    proposal = f'work/authz-{role}'
                    base = refs.get(f'refs/heads/{proposal}') or main_before
                    tip = self.new_commit(repo, role, base, f'{role} module {run_id}')
                    action = f'push HEAD:refs/heads/{proposal} (module)'
                    if role in PROPOSERS:
                        code, _ = self.module(role, action, 'allowed', repo.push, self.url,
                                              f'{tip}:refs/heads/{proposal}', credential, write=True)
                        self.assertEqual(code, 'ok')
                        self.assertEqual(self.branch_head(proposal), tip)
                    else:
                        code, _ = self.denied_push(role, action, repo.push, self.url, f'{tip}:refs/heads/{proposal}',
                                                   credential)
                        self.assertIn(code, ('PUSH_REFUSED', 'PUSH_REJECTED'))
                    direct = self.new_commit(repo, role, main_before, f'direct {role} {run_id}')
                    orphan = self.new_commit(repo, role, None, f'orphan {role} {run_id}')
                    for label, refspec in (('push to the protected branch', f'{direct}:{MAIN}'),
                                           ('force-push', f'+{orphan}:{MAIN}'),
                                           ('delete by push', f':{MAIN}'),
                                           ('push a non-proposal branch', f'{direct}:refs/heads/feature/authz-{role}')):
                        code, _ = self.denied_push(role, f'{label} (module)', repo.push, self.url, refspec,
                                                   credential)
                        self.assertIn(code, ('PUSH_REFUSED', 'PUSH_REJECTED'), label)
                    self.assertIsNone(self.branch_head(f'feature/authz-{role}'))
                    if role == 'builder':
                        code, _ = self.denied_push('anonymous', 'push to a proposal branch without a credential '
                                                   '(module)', repo.push, self.url, f'{tip}:refs/heads/{proposal}',
                                                   None)
                        self.assertEqual(code, 'PUSH_REFUSED')
                self.main_unchanged(main_before, f'the pushes of {role}')
        self.main_unchanged(main_before, 'the matrix')
        self.assertEqual(self.launched, 0)


class TestClone(TransportLive):
    def test_a_module_clone_passes_git_fsck_strict(self):
        """The oracle: git (retained for verification, decision 0014 section 7) checks the module's
        clone. Its launch is the oracle's, outside every module call."""
        clone = self.tmp / 'fsck.git'
        code, refs = self.module('verifier', 'clone for fsck (module)', 'allowed', RA.clone, self.url, clone,
                                 self.credentials['verifier'])
        self.assertEqual(code, 'ok')
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith('GIT_')}
        env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_CEILING_DIRECTORIES=str(self.tmp))
        result = subprocess.run(['git', '--git-dir', str(clone), 'fsck', '--strict', '--no-progress'], env=env,
                                stdin=subprocess.DEVNULL, capture_output=True, timeout=120)
        refs_git = subprocess.run(['git', '--git-dir', str(clone), 'for-each-ref', '--format=%(refname) %(objectname)'],
                                  env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=120)
        RESULTS.append({'role': 'verifier', 'action': 'git fsck --strict of the module clone', 'expected': 'clean',
                        'outcome': result.returncode, 'status': None, 'launches': None,
                        'message': (result.stdout + result.stderr).decode('utf-8', 'replace')[-300:],
                        'refs': len(refs)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout + result.stderr, b'')
        self.assertEqual(dict(line.split(' ') for line in refs_git.stdout.decode().splitlines()), refs)


if __name__ == '__main__':
    unittest.main()
