"""Live authorization tests of the role bots against the running Gitea (plan leaf S-01.2.2).

Opt-in: they run only with AIEH_GITEA_AUTHZ=1 (`task gitea:authz`), on Windows, while Gitea answers
and every bot's Credential Manager entry (`AIEH Gitea bot <role>`) exists. Otherwise each class skips
with its reason, so the ordinary suites never read Credential Manager or write to Gitea. The tests
that need the fixture repository (gitea_roles.py fixture) also skip, with their reason, while it is
absent: creating it is site administration, which Gitea refuses until the site administrator's first
sign-in.

Tokens are read from Credential Manager into memory and sent only in Authorization headers (git
receives an http.extraHeader through GIT_CONFIG_* environment variables of its own process); nothing
prints, logs or asserts on a token. AIEH_GITEA_AUTHZ_REPORT, when set, names a JSON file that
receives every probe (role, action, expectation, HTTP status or git exit code, Gitea's message; for a
protection-audit write, what it would do if Gitea wrongly accepted it), every write the circuit breaker
withheld, and the breaker's state.

**The circuit breaker (Owner authorization OA-16 Act C; live_breaker.py).** Any unexpected acceptance, by
any role, is a SECURITY FAILURE that trips this module's breaker: a write that must be denied answering
2xx, a push that must be denied succeeding, a sign-in with a random password not refused, a pull request
merged, the protected default branch moving (read after each role's push and merge probes), and Gitea
serving the receive-pack advertisement to the protection auditor's read-only token. From then on no write
probe of any role (HTTP or git, allowed or denied, in any class) is sent: each checks the breaker
immediately before it is sent, independently of ``subTest``; the role loops stop, and ``tearDownModule``
fails the run and reports the probe that tripped it and every write not sent. The one write it does not
stop is ``tearDownClass`` closing the proposal PRs that builder and planner opened (a restoration).

**The protection auditor** (role ``protection-audit``: a ``read:repository`` token of a repository
administrator of the fixture, Owner decision OA-16). The other roles' probes are the S-01.2.2 matrix,
unchanged. The auditor's write probes are not: each would change the fixture or create a durable object if
Gitea wrongly accepted it, so each is either made non-mutating, and must be refused by its token scope
(403 "token does not have at least one of required scope(s)"; with the token as a basic-authentication
password, 401 or 403, as in the negative phase; a 2xx is a security failure, any other refusal fails the
test without being one), or not sent:

- *made non-mutating by an absent target*: every write to the fixture's routes (merge, delete the default
  branch, the protection, the settings, the collaborators, a webhook, a deploy token, the transfer, the
  deletion of the repository, an Actions secret) goes to the same route, with the same body, of a
  repository that does not exist (``aieh-authz-fixture/aieh-probe-absent-<hex>``: Gitea's repository
  assignment answers 404 after the ``/repos`` scope check); ``PATCH /admin/users/<absent>``, ``POST
  /admin/users/<absent>/orgs`` (and an empty ``username``) and ``DELETE /users/aieh-owner/tokens/<absent>``
  name an absent user or token;
- *made non-mutating by a body Gitea rejects*: ``POST /admin/users`` (empty ``username`` and ``email``:
  ``Required``), the repository and organization creations (an empty ``name`` or ``username``:
  ``Required``), the token creations for itself, aieh-owner and aieh-site-admin, by token and by the
  token as a basic-authentication password (an empty ``name`` and an unknown scope; a token created anyway
  is revoked at once, a last resort and not a prevention), the user Actions secret (empty ``data``:
  ``Required``, and a name with the reserved prefix ``GITEA_``);
- *git pushes the client withholds after the receive-pack advertisement* (``git push --dry-run``, which
  sends no update, and each refspec one git refuses before sending anyway): a commit unrelated to
  main pushed to main without force (not a fast-forward), and the deletion of an absent branch, forced
  (standing in for the force-push), plain (for the delete by push) and of the absent
  ``feature/authz-protection-audit`` (for the non-proposal branch). Each must end at the advertisement
  with HTTP 403; an advertisement served to the token is a security failure;
- *not sent, reported UNEXERCISED* (the test then fails "not exercised", never counted as passing): the
  web sign-in form with a random password (an acceptance would open a session and record a sign-in; the
  password check is covered by the protection-audit negative phase, basic authentication with a random and
  an empty password) and ``POST /admin/actions/runners/registration-token`` (no body; an acceptance would
  get or create the instance's runner registration token; the ``/admin`` scope refusal is covered by the
  protection-audit negative phase, ``GET /admin/users``).

The bodies' rejections are Gitea's validation as modelled offline (test_live_matrix_safety.py), not re-read
at the 28.3.0 source; the absent targets need no such reading. The scope check precedes every one of them
(the ``/repos``, ``/user``, ``/users``, ``/orgs`` and ``/admin`` groups; S-01.2.2 observed the verifier bot's
identical scope refused on these routes). Its reads are the matrix's own.
"""
from __future__ import annotations

import base64
import importlib.util
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from types import SimpleNamespace

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
LB = _load('aieh_gitea_live_breaker', HERE / 'live_breaker.py')
OPT_IN = os.environ.get('AIEH_GITEA_AUTHZ') == '1'
REPORT = os.environ.get('AIEH_GITEA_AUTHZ_REPORT')
RESULTS: list[dict] = []
DENIED = (401, 403, 404, 405, 409, 422)
REPO = f'/repos/{R.FIXTURE_ORG}/{R.FIXTURE_REPO}'
READS = ('GET', 'HEAD')
AUDITOR = 'protection-audit'
SCOPE_REFUSAL = 'token does not have at least one of required scope(s)'
GIT_403 = 'The requested URL returned error: 403'
EMPTY_TREE = '4b825dc642cb6eb9a060e54bf8d69288fbee4904'
BREAKER = LB.Breaker(lambda row: RESULTS.append(row))
_LIVE: list = []


def live():
    """(context, None) when the live suite can run, else (None, the reason it skips)."""
    if _LIVE:
        return _LIVE[0]
    result = _probe_live()
    _LIVE.append(result)
    return result


def _probe_live():
    if not OPT_IN:
        return None, 'live authorization tests are opt-in: AIEH_GITEA_AUTHZ=1 (task gitea:authz)'
    if os.name != 'nt':
        return None, 'the bot tokens are in Windows Credential Manager'
    try:
        res = G.paths.resolve()
        lay, pinned = G.layout(res), G.pin()
        port = G.read_host_record(lay)['port']
    except (G.GiteaError, G.paths.PathsError) as exc:
        return None, f'Gitea is not installed here ({exc})'
    if not G.healthy(port):
        return None, 'Gitea is not running (task gitea:up)'
    store = G.credential_provider()
    tokens = {role: R.read_token(store, role) for role in R.ROLES}
    if missing := sorted(role for role, token in tokens.items() if token is None):
        return None, f'no Credential Manager entry for {missing} (gitea_roles.py provision)'
    return SimpleNamespace(port=port, tokens=tokens, cli=R.Cli(lay, pinned)), None


def tearDownModule():
    BREAKER.close_run(RESULTS, REPORT)


def message(payload) -> str:
    if isinstance(payload, dict):
        return R.redact(str(payload.get('message', '')))[:160]
    if isinstance(payload, list):
        return f'list of {len(payload)}'
    return R.redact(str(payload))[:160]


# ---------------------------------------------------------------- the protection auditor's write probes

COVERED = 'covered by the protection-audit negative phase'
INVALID = 'made non-mutating: Gitea rejects the body ({})'
ABSENT_REPOSITORY = ('made non-mutating: the repository does not exist (its assignment answers 404 after the '
                     '/repos scope check); route and body as the other roles send them')
ABSENT = 'made non-mutating: {} does not exist (the handler answers 404 after the scope check)'
WITHHELD = 'made non-mutating: git push --dry-run sends no update, and git {} before sending anyway'
NOT_FAST_FORWARD = WITHHELD.format('refuses a push that is not a fast-forward')
ABSENT_DELETE = WITHHELD.format('refuses deleting a branch the remote does not have')
TOKEN_PROBE_BODY = {'name': '', 'scopes': ['aieh-not-a-scope']}   # Required name; an unknown scope
TOKEN_INVALID = INVALID.format('name empty: Required; an unknown scope')
MINT = 'mint an all-scope token with the token as a basic-auth password'


def absent_name() -> str:
    return f'aieh-probe-absent-{secrets.token_hex(4)}'


def absent_repository() -> str:
    return f'/repos/{R.FIXTURE_ORG}/{absent_name()}'


def on_absent_repository(action, method, path, body, absent_repo) -> LB.Probe:
    """A fixture-route write of the auditor, sent to the same route of the absent repository ABSENT_REPO."""
    assert path == REPO or path.startswith(REPO + '/'), path
    return LB.Probe(f'{action} (an absent repository)', method, absent_repo + path[len(REPO):], body,
                    ABSENT_REPOSITORY)


def auditor_admin_probes(absent) -> list[LB.Probe]:
    return [
        LB.Probe('POST /admin/actions/runners/registration-token', None, None, None,
                 'UNEXERCISED: no non-mutating form (no body; an acceptance would get or create the instance\'s '
                 f'runner registration token); the /admin scope refusal is {COVERED} (GET /admin/users)'),
        LB.Probe('POST /admin/users (invalid body)', 'POST', '/admin/users',
                 {'username': '', 'password': '', 'email': ''}, INVALID.format('username and email empty: Required')),
        LB.Probe('PATCH /admin/users/<absent> (make an absent user admin)', 'PATCH', f'/admin/users/{absent}',
                 {'login_name': absent, 'source_id': 0, 'admin': True}, ABSENT.format('the user')),
        LB.Probe('POST /admin/users/<absent>/orgs (an absent user, invalid body)', 'POST',
                 f'/admin/users/{absent}/orgs', {'username': ''},
                 ABSENT.format('the user') + '; and the body: username empty, Required'),
    ]


def auditor_token_probes(user, absent) -> list[LB.Probe]:
    probes = [LB.Probe(f'create a token for {target} (invalid body)', 'POST', f'/users/{target}/tokens',
                       TOKEN_PROBE_BODY, TOKEN_INVALID) for target in (user, G.OWNER, G.SITE_ADMIN)]
    probes.append(LB.Probe(f'delete an absent token of {G.OWNER}', 'DELETE', f'/users/{G.OWNER}/tokens/{absent}',
                           None, ABSENT.format('the token')))
    probes.append(LB.Probe(MINT + ' (invalid body)', 'BASIC POST', f'/users/{user}/tokens', TOKEN_PROBE_BODY,
                           TOKEN_INVALID + '; a token created anyway is revoked at once (a last resort)'))
    return probes


def auditor_creation_probes() -> list[LB.Probe]:
    return [
        LB.Probe('create a repository of its own (invalid body)', 'POST', '/user/repos', {'name': '', 'private': True},
                 INVALID.format('name empty: Required')),
        LB.Probe('create an organization (invalid body)', 'POST', '/orgs', {'username': ''},
                 INVALID.format('username empty: Required')),
        LB.Probe('create a repository in the fixture organization (invalid body)', 'POST',
                 f'/orgs/{R.FIXTURE_ORG}/repos', {'name': ''}, INVALID.format('name empty: Required')),
    ]


def auditor_secret_probe() -> LB.Probe:
    return LB.Probe('write an Actions secret (invalid body, reserved name)', 'PUT',
                    '/user/actions/secrets/GITEA_AIEH_PROBE', {'data': ''},
                    INVALID.format('data empty: Required; and the name\'s GITEA_ prefix is reserved'))


def auditor_sign_in_probe() -> LB.Probe:
    return LB.Probe('web sign-in form with a random password', None, None, None,
                    'UNEXERCISED: an acceptance would open a web session and record a sign-in; the password check '
                    f'is {COVERED} (basic authentication with a random and an empty password)')


def auditor_push_probes(orphan, absent) -> list[LB.Probe]:
    """The auditor's git pushes (``path`` the refspec), each sent with ``git push --dry-run``."""
    return [
        LB.Probe('git push to the protected branch: a commit unrelated to main, without force (--dry-run)', 'PUSH',
                 f'{orphan}:refs/heads/{R.DEFAULT_BRANCH}', None, NOT_FAST_FORWARD),
        LB.Probe('git force-push, standing in: a forced deletion of an absent branch (--dry-run)', 'PUSH',
                 f'+:refs/heads/{absent}', None, ABSENT_DELETE),
        LB.Probe('git delete by push: an absent branch (--dry-run)', 'PUSH', f':refs/heads/{absent}', None,
                 ABSENT_DELETE),
        LB.Probe(f'git push a non-proposal branch, standing in: delete the absent feature/authz-{AUDITOR} '
                 '(--dry-run)', 'PUSH', f':refs/heads/feature/authz-{AUDITOR}', None, ABSENT_DELETE),
    ]


def merge_bodies():
    return ({'Do': 'merge'}, {'Do': 'merge', 'force_merge': True}, {'Do': 'squash'})


def settings_probes(user):
    return (('POST', f'{REPO}/branch_protections', {'rule_name': 'aieh-probe'}),
            ('PATCH', f'{REPO}/branch_protections/{R.DEFAULT_BRANCH}', {'enable_push': True}),
            ('DELETE', f'{REPO}/branch_protections/{R.DEFAULT_BRANCH}', None),
            ('PATCH', REPO, {'description': 'aieh-probe', 'private': False}),
            ('PUT', f'{REPO}/collaborators/{user}', {'permission': 'admin'}),
            ('POST', f'{REPO}/hooks', {'type': 'gitea', 'config': {'url': 'http://127.0.0.1:9/',
                                                                  'content_type': 'json'}}),
            ('POST', f'{REPO}/keys/tokens', {'name': 'aieh-probe', 'scopes': ['read:repository']}),
            ('POST', f'{REPO}/transfer', {'new_owner': user}),
            ('DELETE', REPO, None))


def secret_probes():
    return (('GET', f'{REPO}/actions/secrets', None),
            ('PUT', f'{REPO}/actions/secrets/AIEH_PROBE', {'data': 'probe'}),
            ('GET', f'/orgs/{R.FIXTURE_ORG}/actions/secrets', None),
            ('GET', f'{REPO}/actions/variables', None))


class Live(unittest.TestCase):
    """A class of the live suite: skips with the reason when it cannot run."""

    @classmethod
    def setUpClass(cls):
        ctx, reason = live()
        if ctx is None:
            raise unittest.SkipTest(reason)
        cls.ctx = ctx

    def api(self, role: str | None) -> R.Api:
        return R.Api(self.ctx.port, None if role is None else self.ctx.tokens[role])

    def call(self, role, action, expect, method, path, body=None, headers=None, if_accepted=None):
        if method not in READS:
            BREAKER.check(f'{role or "anonymous"}: {action}')
        status, payload = self.api(role).call(method, path, body, headers)
        row = {'role': role or 'anonymous', 'action': action, 'expected': expect, 'status': status,
               'message': message(payload)}
        if if_accepted is not None:
            row['if accepted'] = if_accepted
        RESULTS.append(row)
        return status, payload

    def denied(self, role, action, method, path, body=None, headers=None):
        status, payload = self.call(role, action, 'denied', method, path, body, headers)
        if method not in READS and 200 <= status < 300:
            raise BREAKER.fail(f'{role or "anonymous"}: {action} ({method} {path}) answered {status}')
        self.assertIn(status, DENIED, f'{role}: {action} answered {status} ({message(payload)})')
        return status, payload

    def allowed(self, role, action, method, path, body=None, headers=None, codes=(200, 201, 204)):
        status, payload = self.call(role, action, 'allowed', method, path, body, headers)
        self.assertIn(status, codes, f'{role}: {action} answered {status} ({message(payload)})')
        return status, payload

    def each_role(self, roles=None):
        """The roles in order, until the breaker trips: then the remaining roles' probes are not sent."""
        roles = list(R.ROLES if roles is None else roles)
        for n, role in enumerate(roles):
            if BREAKER.tripped_by is not None:
                BREAKER.withhold(f'{r}: the remaining probes of {self._testMethodName}' for r in roles[n:])
                return
            yield role

    def mint_with_the_token_as_a_password(self, role, spec, body, if_accepted, refusals):
        action = MINT
        BREAKER.check(f'{role}: {action}')
        basic = base64.b64encode(f'{spec["user"]}:{self.ctx.tokens[role]}'.encode()).decode()
        status, payload = R.Api(self.ctx.port).call('POST', f'/users/{spec["user"]}/tokens', body,
                                                     {'Authorization': 'Basic ' + basic})
        del basic
        row = {'role': role, 'action': action, 'expected': 'denied', 'status': status, 'message': message(payload)}
        if if_accepted is not None:
            row['if accepted'] = if_accepted
        RESULTS.append(row)
        if status == 201 and isinstance(payload, dict) and payload.get('sha1'):
            R.revoke_current(self.ctx.port, payload.pop('sha1'))   # a last resort, not a prevention
        if 200 <= status < 300:
            raise BREAKER.fail(f'{role}: {action} answered {status}')
        self.assertIn(status, refusals)

    # ------------------------------------------------------------ the protection auditor

    def refused_by_scope(self, probe):
        """One auditor write: its scope's 403 passes; a 2xx is a SECURITY FAILURE; any other answer fails."""
        status, payload = self.call(AUDITOR, probe.action, 'refused by scope (403)', probe.method, probe.path,
                                    probe.body, if_accepted=probe.if_accepted)
        if 200 <= status < 300:
            raise BREAKER.fail(f'{AUDITOR}: {probe.action} ({probe.method} {probe.path}) answered {status}')
        self.assertEqual(status, 403, f'{AUDITOR}: {probe.action}: refused with {status}, not by the scope '
                                      f'({message(payload)})')
        self.assertIn(SCOPE_REFUSAL, message(payload), f'{AUDITOR}: {probe.action}')

    def auditor_writes(self, probes, clone=None):
        """Send the auditor's PROBES in order (a security failure stops them, LB.sequence); then fail with every
        other failure and, never counting them as passing, every probe not exercised."""
        unexercised = []

        def send(probe):
            if probe.method is None:
                RESULTS.append({'role': AUDITOR, 'action': probe.action, 'expected': 'denied',
                                'status': 'UNEXERCISED', 'message': probe.if_accepted})
                unexercised.append(f'{probe.action}: {probe.if_accepted}')
            elif probe.method == 'PUSH':
                self.auditor_push(clone, probe)
            elif probe.method == 'BASIC POST':
                self.mint_with_the_token_as_a_password(AUDITOR, R.ROLES[AUDITOR], probe.body, probe.if_accepted,
                                                       (401, 403))
            else:
                self.refused_by_scope(probe)

        failures = LB.sequence(BREAKER, probes, send, self.failureException, prefix=f'{AUDITOR}: ')
        if unexercised:
            failures.append('not exercised: ' + '; '.join(unexercised))
        if failures:
            self.fail('; '.join(failures))

    def auditor_push(self, clone, probe):
        """One auditor push (git push --dry-run): HTTP 403 at the receive-pack advertisement passes. A SECURITY
        FAILURE: a push git reports done, and the advertisement served (git then withheld the update). Any
        other answer fails."""
        action = f'{AUDITOR}: {probe.action}'
        BREAKER.check(action)
        result = git(self.ctx, AUDITOR, 'push', '--dry-run', 'origin', probe.path, cwd=clone)
        err = R.redact(result.stderr.decode('utf-8', 'replace'))
        RESULTS.append({'role': AUDITOR, 'action': probe.action, 'expected': 'refused by scope (HTTP 403 at the '
                        'receive-pack advertisement)', 'status': result.returncode, 'message': err[-200:],
                        'if accepted': probe.if_accepted})
        if GIT_403 in err:
            return
        if result.returncode == 0 or any(mark in err for mark in ('To http', '[rejected]', 'remote ref does not '
                                                                  'exist', 'non-fast-forward', 'fetch first')):
            raise BREAKER.fail(f'{action}: Gitea served the receive-pack advertisement to the read:repository '
                               'token (its scope did not refuse the push); git withheld the update (--dry-run): '
                               f'no update was sent (exit {result.returncode})')
        self.fail(f'{action}: not refused by the scope (exit {result.returncode}: {err[-200:]})')


class TestTokens(Live):
    def test_each_token_is_its_own_bot_with_the_matrix_scopes(self):
        users = self.ctx.cli.users()
        for role, spec in R.ROLES.items():
            with self.subTest(role=role):
                status, body = self.allowed(role, 'read its own token (GET /token)', 'GET', '/token')
                self.assertEqual(sorted(body['scopes']), sorted(spec['scopes']))
                self.assertTrue(body['name'].startswith(f'aieh-{role}-'))
                self.assertEqual(users[spec['user']], {'admin': False, 'type': 'Bot'})

    def test_no_interactive_sign_in(self):
        for role in self.each_role():
            spec = R.ROLES[role]
            with self.subTest(role=role):
                for label, password in (('empty', ''), ('random', secrets.token_urlsafe(18))):
                    basic = base64.b64encode(f'{spec["user"]}:{password}'.encode()).decode()
                    status = G.http_get(self.ctx.port, '/api/v1/repos/search',
                                        headers={'Authorization': 'Basic ' + basic})[0]
                    RESULTS.append({'role': role, 'action': f'basic auth with an {label} password',
                                    'expected': 'denied', 'status': status, 'message': ''})
                    self.assertEqual(status, 401)
                if role == AUDITOR:
                    self.auditor_writes([auditor_sign_in_probe()])
                    continue
                form = urllib.parse.urlencode({'user_name': spec['user'], 'password': secrets.token_urlsafe(18)})
                BREAKER.check(f'{role}: web sign-in form')
                status, _h, body = G.http_get(self.ctx.port, '/user/login', method='POST', body=form.encode(),
                                              headers={'Content-Type': 'application/x-www-form-urlencoded'})
                refused = status == 200 and b'Username or password is incorrect' in body
                RESULTS.append({'role': role, 'action': 'web sign-in form', 'expected': 'denied', 'status': status,
                                'message': 'Username or password is incorrect' if refused else ''})
                if not refused and status < 400:
                    raise BREAKER.fail(f'{role}: the web sign-in form with a random password answered {status}, '
                                       'not refused')
                self.assertTrue(refused)


class TestInstanceWideDenials(Live):
    def test_admin_endpoints(self):
        for role in self.each_role():
            spec = R.ROLES[role]
            with self.subTest(role=role):
                for method, path, body in (
                        ('GET', '/admin/users', None), ('GET', '/admin/emails', None), ('GET', '/admin/orgs', None),
                        ('GET', '/admin/cron', None), ('GET', '/admin/hooks', None),
                        ('POST', '/admin/actions/runners/registration-token', None),
                        ('POST', '/admin/users', {'username': 'aieh-probe-user', 'password': 'Probe-only-0123456789',
                                                  'email': f'aieh-probe-user@{G.EMAIL_DOMAIN}'}),
                        ('PATCH', f'/admin/users/{spec["user"]}', {'login_name': spec['user'], 'source_id': 0,
                                                                  'admin': True}),
                        ('POST', f'/admin/users/{spec["user"]}/orgs', {'username': 'aieh-probe-org'})):
                    if role == AUDITOR and method not in READS:
                        continue   # its writes follow, made non-mutating or not sent
                    self.denied(role, f'{method} {path}', method, path, body)
                if role == AUDITOR:
                    self.auditor_writes(auditor_admin_probes(absent_name()))
        users = self.ctx.cli.users()
        self.assertNotIn('aieh-probe-user', users)
        self.assertFalse(any(users[spec['user']]['admin'] for spec in R.ROLES.values()))

    def test_tokens_of_self_and_others(self):
        for role in self.each_role():
            spec = R.ROLES[role]
            with self.subTest(role=role):
                if role == AUDITOR:
                    for user in (spec['user'], G.OWNER, G.SITE_ADMIN):
                        self.denied(role, f'list tokens of {user}', 'GET', f'/users/{user}/tokens')
                    self.auditor_writes(auditor_token_probes(spec['user'], absent_name()))
                    continue
                for user in (spec['user'], G.OWNER, G.SITE_ADMIN):
                    self.denied(role, f'list tokens of {user}', 'GET', f'/users/{user}/tokens')
                    self.denied(role, f'create a token for {user}', 'POST', f'/users/{user}/tokens',
                                {'name': 'aieh-probe', 'scopes': ['all']})
                self.denied(role, f'delete a token of {G.OWNER}', 'DELETE', f'/users/{G.OWNER}/tokens/1')
                self.mint_with_the_token_as_a_password(role, spec, {'name': 'aieh-probe', 'scopes': ['all']}, None,
                                                       DENIED)

    def test_other_users_and_emails(self):
        for role in R.ROLES:
            with self.subTest(role=role):
                for path in (f'/users/{G.OWNER}', f'/users/{G.SITE_ADMIN}', '/users/search?q=aieh', '/user/emails',
                             '/user', '/admin/emails'):
                    status, payload = self.denied(role, f'GET {path}', 'GET', path)
                    self.assertNotIn(f'@{G.EMAIL_DOMAIN}', json.dumps(payload))

    def test_no_sudo_and_no_impersonation_header(self):
        for role in R.ROLES:
            with self.subTest(role=role):
                for target in (G.OWNER, G.SITE_ADMIN):
                    status, payload = self.denied(role, f'GET /token?sudo={target}', 'GET', f'/token?sudo={target}')
                    self.assertEqual(payload.get('message'), 'Only administrators allowed to sudo.')
                    self.denied(role, f'GET /admin/users with Sudo: {target}', 'GET', '/admin/users',
                                headers={'Sudo': target})
                    status, payload = self.allowed(role, f'GET /token with X-WEBAUTH-USER: {target} (identity '
                                                   'must stay the bot)', 'GET', '/token',
                                                   headers={'X-WEBAUTH-USER': target})
                    self.assertTrue(payload['name'].startswith(f'aieh-{role}-'))
                    self.denied(None, f'anonymous GET /admin/users with X-WEBAUTH-USER: {target}', 'GET',
                                '/admin/users', headers={'X-WEBAUTH-USER': target})

    def test_no_new_repositories_or_organizations(self):
        for role in self.each_role():
            spec = R.ROLES[role]
            with self.subTest(role=role):
                if role == AUDITOR:
                    self.auditor_writes(auditor_creation_probes())
                else:
                    self.denied(role, 'create a repository of its own', 'POST', '/user/repos',
                                {'name': f'aieh-probe-{role}', 'private': True})
                    self.denied(role, 'create an organization', 'POST', '/orgs', {'username': f'aieh-probe-{role}'})
                    self.denied(role, 'create a repository in the fixture organization', 'POST',
                                f'/orgs/{R.FIXTURE_ORG}/repos', {'name': f'aieh-probe-{role}'})
                self.assertEqual(self.api(role).call('GET', f'/repos/{spec["user"]}/aieh-probe-{role}')[0], 404)

    def test_user_secrets(self):
        for role in self.each_role():
            with self.subTest(role=role):
                self.denied(role, 'list its own Actions secrets', 'GET', '/user/actions/secrets')
                if role == AUDITOR:
                    self.auditor_writes([auditor_secret_probe()])
                    continue
                self.denied(role, 'write an Actions secret', 'PUT', '/user/actions/secrets/AIEH_PROBE',
                            {'data': 'probe'})


# ---------------------------------------------------------------- the fixture repository


def git(ctx, role: str, *args: str, cwd: Path) -> subprocess.CompletedProcess:
    """git as the role: the token reaches git only as an http.extraHeader in its own environment."""
    user = R.ROLES[role]['user']
    basic = base64.b64encode(f'{user}:{ctx.tokens[role]}'.encode()).decode()
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='never',
               GIT_AUTHOR_NAME=user, GIT_AUTHOR_EMAIL=f'{user}@{G.EMAIL_DOMAIN}', GIT_COMMITTER_NAME=user,
               GIT_COMMITTER_EMAIL=f'{user}@{G.EMAIL_DOMAIN}', NO_PROXY='127.0.0.1', GIT_CONFIG_COUNT='3',
               GIT_CONFIG_KEY_0='http.extraHeader', GIT_CONFIG_VALUE_0='Authorization: Basic ' + basic,
               GIT_CONFIG_KEY_1='credential.helper', GIT_CONFIG_VALUE_1='',
               GIT_CONFIG_KEY_2='core.autocrlf', GIT_CONFIG_VALUE_2='false')
    return subprocess.run(['git', *args], cwd=str(cwd), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=120)


class Fixture(Live):
    """Needs the fixture: each role gets a clone; builder and planner push their proposal branch and
    open (or reuse) a PR; tearDownClass closes the PRs."""
    url = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        status = R.Api(cls.ctx.port, cls.ctx.tokens['verifier']).call('GET', REPO)[0]
        if status != 200:
            raise unittest.SkipTest(f'the fixture repository answers {status} to the verifier: it is created by '
                                    'gitea_roles.py fixture, after task gitea:finalize-credentials')
        cls.tmp = Path(tempfile.mkdtemp(prefix='aieh-authz-'))
        cls.addClassCleanup(shutil.rmtree, cls.tmp, onexc=lambda f, p, e: (os.chmod(p, 0o700), f(p)))
        cls.url = f'http://{G.LOOPBACK}:{cls.ctx.port}/{R.FIXTURE_ORG}/{R.FIXTURE_REPO}.git'
        cls.clones, cls.pulls, cls.pushes = {}, {}, {}
        for role in R.ROLES:
            clone = cls.tmp / role
            result = git(cls.ctx, role, 'clone', '--quiet', cls.url, str(clone), cwd=cls.tmp)
            cls.clones[role] = clone if result.returncode == 0 else None
            RESULTS.append({'role': role, 'action': 'git clone', 'expected': 'allowed', 'status': result.returncode,
                            'message': R.redact(result.stderr.decode('utf-8', 'replace'))[-160:]})
        run_id = secrets.token_hex(4)
        for role in ('builder', 'planner'):
            branch = f'work/authz-{role}'
            cls.pushes[role] = cls.commit_and_push(role, branch, f'{role} {run_id}')
            BREAKER.check(f'{role}: open a proposal PR')
            api = R.Api(cls.ctx.port, cls.ctx.tokens[role])
            status, body = api.call('POST', f'{REPO}/pulls', {'head': branch, 'base': R.DEFAULT_BRANCH,
                                                               'title': f'authorization probe ({role})'})
            if status in (409, 422):
                _s, open_pulls = api.call('GET', f'{REPO}/pulls?state=open&limit=50')
                body = next((p for p in open_pulls or [] if p['head']['ref'] == branch), None)
            RESULTS.append({'role': role, 'action': 'open a proposal PR', 'expected': 'allowed', 'status': status,
                            'message': message(body)})
            cls.pulls[role] = (status, body.get('number') if isinstance(body, dict) else None)

    @classmethod
    def commit_and_push(cls, role, branch, text, refspec=None, force=False) -> int:
        clone = cls.clones[role]
        if clone is None:
            return -1
        remote = git(cls.ctx, role, 'ls-remote', '--heads', 'origin', branch, cwd=clone).stdout.strip()
        start = f'origin/{branch}' if remote else f'origin/{R.DEFAULT_BRANCH}'
        git(cls.ctx, role, 'fetch', '--quiet', 'origin', cwd=clone)
        git(cls.ctx, role, 'checkout', '--quiet', '-B', branch, start, cwd=clone)
        (clone / f'{role}.txt').write_text(text + '\n', encoding='utf-8')
        git(cls.ctx, role, 'add', f'{role}.txt', cwd=clone)
        git(cls.ctx, role, 'commit', '--quiet', '-m', text, cwd=clone)
        args = ['push', '--quiet', *(['--force'] if force else []), 'origin', refspec or f'HEAD:refs/heads/{branch}']
        BREAKER.check(f'{role}: git {" ".join(args[2:])}')
        result = git(cls.ctx, role, *args, cwd=clone)
        RESULTS.append({'role': role, 'action': f'git {" ".join(args[2:])}', 'expected': 'see test',
                        'status': result.returncode,
                        'message': R.redact(result.stderr.decode('utf-8', 'replace'))[-200:]})
        return result.returncode

    @classmethod
    def tearDownClass(cls):
        for role, (_status, number) in getattr(cls, 'pulls', {}).items():
            if number:   # a restoration: not stopped by the breaker
                R.Api(cls.ctx.port, cls.ctx.tokens[role]).call('PATCH', f'{REPO}/pulls/{number}', {'state': 'closed'})

    def head(self, branch=R.DEFAULT_BRANCH) -> str:
        return self.api('verifier').call('GET', f'{REPO}/branches/{urllib.parse.quote(branch, safe="")}')[1]['commit']['id']

    def main_unchanged(self, before, during):
        """The default branch still at BEFORE; it moved: a SECURITY FAILURE."""
        now = self.head()
        if now != before:
            raise BREAKER.fail(f'{R.DEFAULT_BRANCH} moved during {during} ({before} -> {now})')

    def absent_branch(self, name):
        """NAME must not exist (its deletion is then withheld): else the test fails, not exercised."""
        status = self.api('verifier').call('GET', f'{REPO}/branches/{urllib.parse.quote(name, safe="")}')[0]
        if status != 404:
            self.fail(f'not exercised: the branch {name} answers {status}, so its deletion would not be withheld')


class TestFixtureAllowed(Fixture):
    def test_every_role_reads_the_repository(self):
        for role in R.ROLES:
            with self.subTest(role=role):
                self.allowed(role, 'read the repository', 'GET', REPO)
                self.assertIsNotNone(self.clones[role], f'{role} could not clone')

    def test_builder_and_planner_push_a_proposal_branch_and_open_a_pr(self):
        for role in ('builder', 'planner'):
            with self.subTest(role=role):
                self.assertEqual(self.pushes[role], 0)
                status, number = self.pulls[role]
                self.assertIn(status, (201, 409, 422))
                self.assertIsNotNone(number)

    def test_reviewer_submits_a_review(self):
        number = self.pulls['builder'][1]
        self.allowed('reviewer', 'submit an approving review', 'POST', f'{REPO}/pulls/{number}/reviews',
                     {'event': 'APPROVED', 'body': 'authorization probe review'})

    def test_verifier_reads_the_protected_ref_the_pr_and_a_blob(self):
        _s, branch = self.allowed('verifier', 'read the protected default branch', 'GET',
                                  f'{REPO}/branches/{R.DEFAULT_BRANCH}')
        self.assertTrue(branch['protected'])
        _s, pull = self.allowed('verifier', 'read a PR (merged_by)', 'GET', f'{REPO}/pulls/{self.pulls["builder"][1]}')
        self.assertIn('merged_by', pull)
        self.allowed('verifier', 'read a blob', 'GET', f'{REPO}/raw/README.md?ref={R.DEFAULT_BRANCH}')


class TestFixtureDenied(Fixture):
    def test_nobody_merges_into_the_protected_branch(self):
        before = self.head()
        absent_repo = absent_repository()
        for number in {n for _s, n in self.pulls.values() if n}:
            for role in self.each_role():
                with self.subTest(role=role, pull=number):
                    if role == AUDITOR:
                        self.auditor_writes([on_absent_repository(f'merge PR ({json.dumps(body)})', 'POST',
                                                                  f'{REPO}/pulls/{number}/merge', body, absent_repo)
                                             for body in merge_bodies()])
                        continue
                    for body in merge_bodies():
                        self.denied(role, f'merge PR ({json.dumps(body)})', 'POST', f'{REPO}/pulls/{number}/merge',
                                    body)
            if self.api('verifier').call('GET', f'{REPO}/pulls/{number}')[1]['merged']:
                raise BREAKER.fail(f'PR {number} was merged during the merge probes')
            self.main_unchanged(before, f'the merge probes of PR {number}')
        self.main_unchanged(before, 'the merge probes')

    def test_no_push_force_push_or_deletion_of_protected_refs(self):
        before = self.head()
        for role in self.each_role():
            with self.subTest(role=role):
                clone = self.clones[role]
                self.assertIsNotNone(clone)
                if role == AUDITOR:
                    self.auditor_pushes(clone)
                else:
                    self.push_probes(role, clone)
                self.main_unchanged(before, f'the push probes of {role}')
        for role in self.each_role(('reviewer', 'verifier')):
            with self.subTest(role=role, branch='work/*'):
                code = self.commit_and_push(role, f'work/authz-{role}', f'proposal {role}')
                if code == 0:
                    raise BREAKER.fail(f'{role}: a push of work/authz-{role} succeeded')
                self.assertNotEqual(code, 0)
        self.main_unchanged(before, 'the push probes')

    def push_probes(self, role, clone):
        code = self.commit_and_push(role, R.DEFAULT_BRANCH, f'direct {role}')
        if code == 0:
            raise BREAKER.fail(f'{role}: a push to the protected {R.DEFAULT_BRANCH} succeeded')
        self.assertNotEqual(code, 0)
        orphan = git(self.ctx, role, 'commit-tree', EMPTY_TREE, '-m', 'orphan', cwd=clone).stdout.decode().strip()
        for args, label in ((['push', 'origin', f'+{orphan}:refs/heads/{R.DEFAULT_BRANCH}'], 'force-push'),
                            (['push', 'origin', f':refs/heads/{R.DEFAULT_BRANCH}'], 'delete by push'),
                            (['push', 'origin', f'HEAD:refs/heads/feature/authz-{role}'],
                             'push a non-proposal branch')):
            BREAKER.check(f'{role}: git {label}')
            result = git(self.ctx, role, *args, cwd=clone)
            RESULTS.append({'role': role, 'action': f'git {label}', 'expected': 'denied',
                            'status': result.returncode,
                            'message': R.redact(result.stderr.decode('utf-8', 'replace'))[-200:]})
            if result.returncode == 0:
                raise BREAKER.fail(f'{role}: git {label} succeeded')
            self.assertNotEqual(result.returncode, 0, label)
        self.denied(role, 'delete the default branch (API)', 'DELETE', f'{REPO}/branches/{R.DEFAULT_BRANCH}')

    def auditor_pushes(self, clone):
        absent = absent_name()
        for name in (absent, f'feature/authz-{AUDITOR}'):
            self.absent_branch(name)
        orphan = git(self.ctx, AUDITOR, 'commit-tree', EMPTY_TREE, '-m', 'orphan', cwd=clone).stdout.decode().strip()
        self.auditor_writes([*auditor_push_probes(orphan, absent),
                             on_absent_repository('delete the default branch (API)', 'DELETE',
                                                  f'{REPO}/branches/{R.DEFAULT_BRANCH}', None, absent_repository())],
                            clone=clone)

    def test_no_change_to_protection_or_repository_settings(self):
        for role in self.each_role():
            with self.subTest(role=role):
                user = R.ROLES[role]['user']
                if role == AUDITOR:
                    absent_repo = absent_repository()
                    self.auditor_writes([on_absent_repository(f'{method} {path}', method, path, body, absent_repo)
                                         for method, path, body in settings_probes(user)])
                    continue
                for method, path, body in settings_probes(user):
                    self.denied(role, f'{method} {path}', method, path, body)
        _s, info = self.api('verifier').call('GET', REPO)
        self.assertTrue(info['private'])

    def test_no_repository_or_organization_secrets(self):
        for role in self.each_role():
            with self.subTest(role=role):
                writes = []
                for method, path, body in secret_probes():
                    if role == AUDITOR and method not in READS:
                        writes.append(on_absent_repository(f'{method} {path}', method, path, body, absent_repository()))
                        continue
                    self.denied(role, f'{method} {path}', method, path, body)
                if writes:
                    self.auditor_writes(writes)

    def test_verifier_and_reviewer_hold_no_proposal_rights(self):
        self.denied('verifier', 'open a PR', 'POST', f'{REPO}/pulls',
                    {'head': 'work/authz-builder', 'base': R.DEFAULT_BRANCH, 'title': 'verifier probe'})
        self.denied('verifier', 'submit a review', 'POST', f'{REPO}/pulls/{self.pulls["builder"][1]}/reviews',
                    {'event': 'COMMENT', 'body': 'verifier probe'})


class TestExecutor(unittest.TestCase):
    @unittest.skip('not applicable: no executor principal or executor API exists (G-04.x); executor-action denial '
                   'is carried to G-04.2.1')
    def test_bots_cannot_perform_executor_actions(self):
        pass
