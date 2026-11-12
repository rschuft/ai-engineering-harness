"""Live tests of the protection auditor (Owner decision OA-16; decision 0012 point 6): opt-in, never by default.

Each phase is a separate Owner act and runs only when AIEH_PROTECTION_AUDIT_LIVE names it, on Windows, under
the tools interpreter, while the managed Gitea answers and the Credential Manager entry "AIEH Gitea bot
protection-audit" exists (gitea_roles.py provision) and the fixture repository answers the auditor
(gitea_roles.py fixture). Otherwise every class skips with its reason, so the ordinary suites never read
Credential Manager or reach Gitea. Tokens are read from the credential provider into memory by the product
code (gitea_roles.read_token) and sent only in Authorization headers; nothing prints, logs or asserts on a
token. AIEH_PROTECTION_AUDIT_REPORT, when set, names a JSON file that receives every probe (action,
expectation, HTTP status or module code, Gitea's message, and for a write what it would do if Gitea
wrongly accepted it), every write probe the circuit breaker withheld, and the breaker's state.

**Phase ``negative``** (``AIEH_PROTECTION_AUDIT_LIVE=negative``; reads the auditor's and the verifier bot's
entries). The auditor's token (read:repository, of a repository administrator of the fixture) must:

- identify itself: ``GET /token`` answers its login aieh-bot-protection-audit and scopes exactly
  ``read:repository``; a password (random, or the token itself as a basic-authentication password on a
  user route) gets no more;
- read: the fixture's rules (200, exactly the declared rule names) and its repository view with
  ``permissions.admin`` true; control: the verifier bot's token (a read collaborator) gets 403 on the rules
  (``reqAdmin``);
- be refused every write, each by its scope (403 "token does not have at least one of required scope(s)"):
  modify the protection (PATCH main, DELETE an absent rule, POST the priorities with no ids), change
  collaborators or permissions (PUT its own and the verifier's permission, DELETE an absent collaborator,
  DELETE an absent team), change the repository's settings (PATCH), add a deploy key or deploy token, a
  webhook, push (an API file write, and a git push over smart HTTP through the repository module:
  ``PUSH_REFUSED``), merge (an absent pull request), create a repository (its own, or in the fixture
  organization);
- not escape its repository: ``GET /repos/search`` lists the fixture only; the organization, user and admin
  routes are refused (403 by scope); ``sudo`` is refused ("Only administrators allowed to sudo."); every
  repository the escape probe reads answers 404 or 403 on its rules: by default
  ``aieh-authz-fixture/escape-probe``, the private, empty repository with no collaborators that
  ``gitea_roles.py escape-probe`` creates as the site administrator (a separate Owner act, run before this
  phase); AIEH_PROTECTION_AUDIT_OTHER_REPOS, when set, names others instead (comma-separated; the auditor is
  no collaborator of them), and set but empty, the probe fails as not exercised. Gitea answers 404 both for a
  repository the token cannot see and for one that does not exist, so this phase cannot tell them apart: the
  escape-probe act's report (``state``, ``observed``) is what shows that the repository exists.

**What a wrongly accepted write would do.** Not every write probe is inherently harmless: a write with a
valid body that Gitea accepted would change the fixture or create a durable object. Each probe is therefore
one of two kinds (``write_probes``, ``push_probes``; the report names the kind of each):

- *harmless*: it asks for what already holds, so an acceptance leaves every value as it was (Gitea may record
  a new update time): the PATCH of main (its ``required_approvals`` as the snapshot just read it), the PATCH of
  the repository (its ``allow_merge_commits`` as just read), the PUT of the auditor's and of the verifier
  bot's permission (each as just read; the probes are not sent when a permission read is not one a PUT can
  express); the DELETE of an absent rule, collaborator and team; the priorities POST with no ids; the merge
  of an absent pull request;
- *made non-mutating*: a body Gitea's validation rejects, so an acceptance by the scope still creates
  nothing: the deploy key, deploy token and webhook (empty required fields); the API file write (its
  ``branch`` is an absent, invalid reference name, ``GitRefName``, and no ``new_branch``: the handler also
  refuses a branch that does not exist); both repository creations (an empty ``name``: ``Required``); the
  token creation with the token as a password (an empty ``name`` and an unknown scope; a token created
  anyway is still revoked at once, a last resort and not a prevention); the git pushes, which the repository
  module refuses before it sends any update: a commit unrelated to main, pushed to main without force (not a
  fast-forward), and the deletion of an absent ``work/`` branch.

No write probe is left unexercised. Each probe still requires its scope's 403 (``PUSH_REFUSED`` for git).
These bodies rely on one order in Gitea 28.3.0: the token-scope check (``tokenRequiresScopes``, group
middleware of ``/repos``, ``/user``, ``/users`` and ``/orgs``; for git, ``CheckRepoScopedToken`` at the
receive-pack advertisement) runs before the route's own handlers, the first of which is the body binding
(``bind``, answering 422). The scope's place is read at the pinned source (evidence
P-04.2-protection-check-recommendation.md section 2.1, items 3, 6 and 9); ``bind``'s place at route level is
Gitea's router convention, not re-read at 28.3.0. If the order were otherwise, an HTTP probe would be
answered 422 or 404: still nothing created, and the test fails (the scope did not refuse it); it never
passes. A git probe answered ``PUSH_REJECTED`` (Gitea served the receive-pack advertisement, so the write
scope did not refuse the token; the module sent no update) is a security failure.

**Security failures and the circuit breaker.** Any write that answers 2xx, a push that succeeds or that the
scope does not refuse (``PUSH_REJECTED``: the advertisement was served), a read of another repository's
rules, or a change of the snapshot (main's head, the rules, the roster and each
collaborator's permission, the settings, the branches and tags, the deploy keys and tokens, the webhooks,
the teams, and the repositories the auditor sees) is a SECURITY FAILURE. The first one trips a circuit
breaker of this module, independent of unittest: from then on every write probe, HTTP or git, in any class
run later in this process, is not sent and fails at once naming the trip, and a write sequence stops at the
probe that tripped it (no ``subTest`` continues it). ``tearDownModule`` then fails the run and the report
records the probe that tripped it and every write not sent. **The remedy is to revoke the token at once
(``gitea_roles.py retire protection-audit``, an Owner-approved act) and report.** What the auditor's token
cannot read is not in the snapshot: the organization's repository list (``/orgs/{org}/repos``, organization
scope) and the auditor's own (``/user/repos``, user scope); ``/repos/search`` lists every repository the
auditor can see. The site administrator's snapshot outside this test covers the rest. A refusal other than
403 (for example 404 or 422) fails the test without being a security failure: the scope did not refuse it.
``DELETE /api/v1/token`` is never sent: it needs no scope and would revoke the token itself.

**Phase ``qualify``** (``AIEH_PROTECTION_AUDIT_LIVE=qualify``; site administration as aieh-site-admin by
basic authentication with its harness-held password, as ``gitea_roles.py fixture`` does) runs one explicit
sequence (``Qualification``; Owner authorization OA-16 Act D), not a ``subTest`` loop:

- *precondition*, before any mutation: ``GET /token`` with the auditor's token names its login and exactly
  ``read:repository``; the protection check (protection_check.verify) answers ``verified``, its digest the
  baseline: AIEH_PROTECTION_AUDIT_BASELINE when set (it must then be ``sha256:<64 hex>`` and equal), else the
  first verdict's (the report names the source); the site administrator's read-back (``gitea_roles.read_fixture``
  and the collaborator roster) equals the complete declaration (the settings, the collaborator permissions,
  the rule set and all 34 fields of every rule, list fields compared sorted as the check does);
- *five scenarios*, in order, each only after the previous passed every check: main's
  ``block_admin_merge_override`` false; main's priority 5 (Gitea then enforces ``**`` on main: precedence); an
  extra rule ``aieh-qualify/*``; the verifier bot raised to admin; squash merges allowed. Each injection is
  sent once (2xx required); the check must answer ``drift`` with a problem naming it; one restoration follows
  (the extra rule deleted if present, then one ``gitea_roles.apply_fixture``, the total declaration); then the
  independent read-back must equal the declaration and the check must answer ``verified`` with the baseline
  digest;
- *after the fifth*: the complete declaration read back, the baseline digest, no ``aieh-qualify/*`` rule, the
  verifier bot back to ``read``.

Any failed check, an injection answering other than 2xx, or any exception (an uncertain outcome) sets a stop
latch: no later injection is ever sent. When the stop follows a sent injection, one restoration attempt is made
for it unless one was already made; the final state is then read once (read-back and verdict) and reported,
with the failed check and the injections not sent, and the test fails. No mutation or restoration is retried.
These API changes leave no audit event at Gitea 28.3.0 (finding F-B).
"""
from __future__ import annotations

import base64
import importlib.util
import json
import os
import re
import secrets
import shutil
import sys
import tempfile
import time
import unittest
import urllib.parse
from pathlib import Path
from types import SimpleNamespace
from typing import NamedTuple

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
PC = _load('aieh_gitea_protection_check', HERE.parent / 'protection_check.py')
PHASES = ('negative', 'qualify')
PHASE = os.environ.get('AIEH_PROTECTION_AUDIT_LIVE', '')
REPORT = os.environ.get('AIEH_PROTECTION_AUDIT_REPORT')
ESCAPE_PROBE = f'{R.FIXTURE_ORG}/{R.ESCAPE_PROBE_REPO}'


def other_repos(environ) -> list[str]:
    """The repositories the escape probe reads: AIEH_PROTECTION_AUDIT_OTHER_REPOS (comma-separated) when it is
    set, else the escape-probe repository that gitea_roles.py escape-probe creates."""
    named = environ.get('AIEH_PROTECTION_AUDIT_OTHER_REPOS')
    if named is None:
        return [ESCAPE_PROBE]
    return [r.strip() for r in named.split(',') if r.strip()]


OTHER_REPOS = other_repos(os.environ)
REPOSITORY = f'{R.FIXTURE_ORG}/{R.FIXTURE_REPO}'
REPO = f'/repos/{REPOSITORY}'
MAIN = f'refs/heads/{R.DEFAULT_BRANCH}'
RESULTS: list[dict] = []
SCOPE_REFUSAL = 'token does not have at least one of required scope(s)'
LIST_LIMIT = 50  # PC.PAGE's page size: a list this long may be incomplete
READS = ('GET', 'HEAD')
_LIVE: list = []


# ---------------------------------------------------------------- the circuit breaker


class Breaker:
    """Tripped by the first security failure of this process; from then on no write probe is sent.

    Independent of unittest: every write probe calls ``check`` immediately before it sends anything, and
    ``check`` raises once the breaker is tripped, so no ``subTest``, ``failfast`` setting or failure report
    decides whether a later write goes out."""

    def __init__(self):
        self.tripped_by = None   # the first security failure's detail
        self.withheld = []       # the write probes not sent since

    def trip(self, detail):
        if self.tripped_by is None:
            self.tripped_by = detail

    def check(self, action):
        """Before a write probe is sent: raise BreakerOpen (and record it withheld) once tripped."""
        if self.tripped_by is not None:
            self.withhold([action])
            raise BreakerOpen(action, self.tripped_by)

    def withhold(self, actions):
        for action in actions:
            self.withheld.append(action)
            RESULTS.append({'action': action, 'expected': 'refused by scope', 'status': 'not sent',
                            'message': 'the circuit breaker tripped earlier; this write was not sent'})

    def record(self):
        return {'action': 'circuit breaker', 'tripped_by': self.tripped_by, 'not_sent': list(self.withheld)}


BREAKER = Breaker()


class SecurityFailure(AssertionError):
    """The read-only token wrote, or the fixture changed under it: stop, revoke the token, report. Creating one
    trips the circuit breaker."""

    def __init__(self, detail):
        BREAKER.trip(detail)
        super().__init__(f'SECURITY FAILURE: {detail}. Remedy: revoke the token at once (gitea_roles.py retire '
                         'protection-audit, an Owner-approved act) and report')


class BreakerOpen(SecurityFailure):
    """A write probe not sent because the circuit breaker had tripped (it does not trip it again)."""

    def __init__(self, action, tripped_by):
        AssertionError.__init__(self, f'SECURITY FAILURE earlier in this run ({tripped_by}): {action} was not '
                                      'sent, nor is any later write. Remedy: revoke the token at once '
                                      '(gitea_roles.py retire protection-audit, an Owner-approved act) and report')


def live(phase):
    """(context, None) when PHASE can run, else (None, the reason it skips)."""
    if not _LIVE:
        _LIVE.append(_probe_live())
    ctx, reason = _LIVE[0]
    if ctx is not None and PHASE != phase:
        return None, f'phase {PHASE!r} runs; this class belongs to phase {phase!r}'
    return ctx, reason


def _probe_live():
    if PHASE not in PHASES:
        return None, ('the live protection-auditor tests are opt-in, each phase an Owner act: '
                      'AIEH_PROTECTION_AUDIT_LIVE=negative or =qualify')
    if os.name != 'nt':
        return None, 'the tokens are in Windows Credential Manager'
    try:
        res = G.paths.resolve()
        port = G.read_host_record(G.layout(res))['port']
    except (G.GiteaError, G.paths.PathsError) as exc:
        return None, f'Gitea is not installed here ({exc})'
    if not G.healthy(port):
        return None, 'Gitea is not running (task gitea:up)'
    provider = G.credential_provider()
    token = R.read_token(provider, 'protection-audit')
    if token is None:
        return None, f'no Credential Manager entry {PC.ENTRY!r} (gitea_roles.py provision, an Owner act)'
    status = R.Api(port, token).call('GET', REPO)[0]
    if status != 200:
        return None, f'the fixture answers {status} to the auditor (gitea_roles.py fixture, an Owner act)'
    return SimpleNamespace(port=port, provider=provider, token=token, http=None), None


def tearDownModule():
    tripped = BREAKER.tripped_by is not None
    if tripped:
        RESULTS.append(BREAKER.record())
    if REPORT and RESULTS:
        Path(REPORT).write_text(json.dumps(RESULTS, indent=1) + '\n', encoding='utf-8')
    if tripped:
        raise AssertionError(f'SECURITY FAILURE in this run: the circuit breaker tripped at {BREAKER.tripped_by}; '
                             f'{len(BREAKER.withheld)} later write probe(s) were not sent '
                             f'{BREAKER.withheld}. Remedy: revoke the token at once (gitea_roles.py retire '
                             'protection-audit, an Owner-approved act) and report')


def message(payload) -> str:
    if isinstance(payload, dict):
        return R.redact(str(payload.get('message', '')))[:200]
    if isinstance(payload, list):
        return f'list of {len(payload)}'
    return R.redact(str(payload))[:200]


# ---------------------------------------------------------------- the write probes

HARMLESS_CURRENT = 'harmless: the value just read, so nothing changes'
HARMLESS_ABSENT = 'harmless: the object does not exist'
INVALID = 'made non-mutating: Gitea rejects the body ({})'
NOT_FAST_FORWARD = 'made non-mutating: the repository module refuses a push that is not a fast-forward before sending'
ABSENT_DELETE = 'made non-mutating: the repository module refuses deleting an absent reference before sending'
PERMISSIONS = ('read', 'write', 'admin')  # what PUT /collaborators/{user} accepts


class Probe(NamedTuple):
    action: str
    method: str
    path: str
    body: object
    if_accepted: str   # what the probe would do if Gitea wrongly accepted it


def write_probes(before, absent) -> list[Probe]:
    """The HTTP write probes, each harmless or made non-mutating if Gitea wrongly accepted it. BEFORE is the
    snapshot just read: the PATCH and PUT bodies repeat its values. ABSENT names no rule, collaborator, team or
    branch. ValueError when a current value cannot be repeated (then nothing may be sent)."""
    main = next((r for r in before['rules'] if isinstance(r, dict) and r.get('rule_name') == R.DEFAULT_BRANCH),
                None)
    if main is None or not isinstance(main.get('required_approvals'), int):
        raise ValueError(f'no rule {R.DEFAULT_BRANCH!r} with its required_approvals was read')
    merge_commits = before['settings'].get('allow_merge_commits')
    if not isinstance(merge_commits, bool):
        raise ValueError(f'allow_merge_commits was read as {merge_commits!r}')
    verifier = R.ROLES['verifier']['user']
    permission = {}
    for login in (PC.AUDITOR, verifier):
        permission[login] = before['permissions'].get(login)
        if permission[login] not in PERMISSIONS:
            raise ValueError(f'the permission of {login} was read as {permission[login]!r}, which a PUT cannot '
                             'repeat')
    invalid_ref = f'{absent}..invalid'   # no branch, and no valid reference name (git check-ref-format: '..')
    return [
        Probe('modify the protection: PATCH main (its current required_approvals)', 'PATCH',
              f'{REPO}/branch_protections/main', {'required_approvals': main['required_approvals']}, HARMLESS_CURRENT),
        Probe('modify the protection: DELETE an absent rule', 'DELETE', f'{REPO}/branch_protections/{absent}', None,
              HARMLESS_ABSENT),
        Probe('modify the protection: POST the priorities with no ids', 'POST', f'{REPO}/branch_protections/priority',
              {'ids': []}, 'harmless: no rule named, nothing reordered'),
        Probe('change permissions: PUT its own (current) permission', 'PUT', f'{REPO}/collaborators/{PC.AUDITOR}',
              {'permission': permission[PC.AUDITOR]}, HARMLESS_CURRENT),
        Probe('change permissions: PUT the verifier bot\'s (current) permission', 'PUT',
              f'{REPO}/collaborators/{verifier}', {'permission': permission[verifier]}, HARMLESS_CURRENT),
        Probe('change collaborators: DELETE an absent collaborator', 'DELETE', f'{REPO}/collaborators/{absent}', None,
              HARMLESS_ABSENT),
        Probe('change teams: DELETE an absent team', 'DELETE', f'{REPO}/teams/{absent}', None, HARMLESS_ABSENT),
        Probe('change the settings: PATCH the repository (its current allow_merge_commits)', 'PATCH', REPO,
              {'allow_merge_commits': merge_commits}, HARMLESS_CURRENT),
        Probe('add a deploy key (invalid body)', 'POST', f'{REPO}/keys', {'title': '', 'key': ''},
              INVALID.format('title and key empty: Required')),
        Probe('add a deploy token (invalid body)', 'POST', f'{REPO}/keys/tokens', {'title': ''},
              INVALID.format('title empty: Required')),
        Probe('add a webhook (invalid body)', 'POST', f'{REPO}/hooks', {'type': '', 'config': {}},
              INVALID.format('type and config empty: Required')),
        Probe('push through the API: a file on an absent, invalid branch', 'POST',
              f'{REPO}/contents/aieh-audit-probe.txt',
              {'content': base64.b64encode(b'probe\n').decode(), 'message': 'probe', 'branch': invalid_ref},
              INVALID.format('branch not a valid reference name: GitRefName; absent, and no new_branch')),
        Probe('merge: an absent pull request', 'POST', f'{REPO}/pulls/999999/merge', {'Do': 'merge'},
              HARMLESS_ABSENT),
        Probe('create a repository of its own (invalid body)', 'POST', '/user/repos', {'name': '', 'private': True},
              INVALID.format('name empty: Required')),
        Probe('create a repository in the fixture organization (invalid body)', 'POST',
              f'/orgs/{R.FIXTURE_ORG}/repos', {'name': '', 'private': True}, INVALID.format('name empty: Required')),
    ]


TOKEN_PROBE_BODY = {'name': '', 'scopes': ['aieh-not-a-scope']}  # Required name; an unknown scope


def push_probes(orphan, absent) -> list[Probe]:
    """The git push probes (``path`` the refspec): ORPHAN, a commit with no parent, to main without
    force (not a fast-forward of main: the module refuses it before sending), and the deletion of the absent
    branch work/ABSENT (the module refuses deleting a reference the remote does not have). Either reaches the
    receive-pack advertisement, where Gitea checks the write scope, and sends no update."""
    return [Probe('git push to main: a commit unrelated to main, without force (repository module)', 'PUSH',
                  f'{orphan}:{MAIN}', None, NOT_FAST_FORWARD),
            Probe('git push a proposal branch: delete an absent work/ branch (repository module)', 'PUSH',
                  f':refs/heads/work/{absent}', None, ABSENT_DELETE)]


def incomplete(snap) -> list[str]:
    """What of a snapshot was not read whole: an unreadable or unexpected answer, or a list as long as a page."""
    problems = []

    def visit(name, value):
        if isinstance(value, dict) and {'unreadable', 'unexpected'} & set(value):
            problems.append(f'{name}: {value}')
        elif isinstance(value, list) and len(value) >= LIST_LIMIT:
            problems.append(f'{name}: {len(value)} entries, a full page (may be incomplete)')

    for name, value in snap.items():
        if name == 'permissions' and isinstance(value, dict) and 'unreadable' not in value:
            for login, level in value.items():
                visit(f'the permission of {login}', level)
        else:
            visit(name, value)
    return problems


def changed(before, after) -> list[str]:
    return sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))


class Live(unittest.TestCase):
    PHASE_OF_CLASS = ''

    @classmethod
    def setUpClass(cls):
        ctx, reason = live(cls.PHASE_OF_CLASS)
        if ctx is None:
            raise unittest.SkipTest(reason)
        cls.ctx = ctx

    def http(self):
        """The HTTP function every request goes through (gitea_host.http_get live; a fake offline)."""
        return getattr(self.ctx, 'http', None) or G.http_get

    def call(self, action, expect, method, path, body=None, headers=None, token=None, if_accepted=None):
        if method not in READS:
            BREAKER.check(action)
        api = R.Api(self.ctx.port, self.ctx.token if token is None else token, self.http())
        status, payload = api.call(method, path, body, headers)
        row = {'action': action, 'expected': expect, 'status': status, 'message': message(payload)}
        if if_accepted is not None:
            row['if accepted'] = if_accepted
        RESULTS.append(row)
        return status, payload

    def snapshot(self):
        """What a wrongly accepted write could change and the auditor's token can read: main's head, the rules,
        the roster and each collaborator's permission, the settings, the branches and tags (name and commit),
        the deploy keys and deploy tokens (GET /keys lists both), the webhooks, the teams, and the
        repositories the auditor sees (GET /repos/search). A read that fails is kept as {'unreadable': status}
        (an unexpected shape as {'unexpected': ...}), so a change of what is readable is a change too."""

        def read(label, path, extract):
            status, payload = self.call(f'snapshot: {label}', 'allowed', 'GET', path)
            if status != 200:
                return {'unreadable': status, 'message': message(payload)}
            try:
                return extract(payload)
            except (KeyError, TypeError, AttributeError, IndexError):
                return {'unexpected': message(payload)}

        snap = {
            'main': read('main', f'{REPO}/branches/{R.DEFAULT_BRANCH}', lambda b: b['commit']['id']),
            'rules': read('the rules', f'{REPO}/branch_protections',
                          lambda rules: [{k: r.get(k) for k in PC.FIELDS} for r in rules]),
            'roster': read('the collaborators', f'{REPO}/collaborators?{PC.PAGE}',
                           lambda roster: sorted(c['login'] for c in roster)),
            'settings': read('the repository', REPO, lambda repo: {k: repo.get(k) for k in R.repository_settings()}),
            'branches': read('the branches', f'{REPO}/branches?{PC.PAGE}',
                             lambda found: sorted([b['name'], b['commit']['id']] for b in found)),
            'tags': read('the tags', f'{REPO}/tags?{PC.PAGE}',
                         lambda found: sorted([t['name'], t['id']] for t in found)),
            'deploy_keys': read('the deploy keys and tokens', f'{REPO}/keys?{PC.PAGE}',
                                lambda found: sorted([k['id'], k.get('title'), k.get('read_only')] for k in found)),
            'webhooks': read('the webhooks', f'{REPO}/hooks?{PC.PAGE}',
                             lambda found: sorted([h['id'], h.get('type'), h.get('active')] for h in found)),
            'teams': read('the teams', f'{REPO}/teams', lambda found: sorted(t['name'] for t in found)),
            'repositories': read('the repositories the auditor sees', f'/repos/search?{PC.PAGE}',
                                 lambda found: sorted(r['full_name'] for r in found['data'])),
        }
        roster = snap['roster']
        snap['permissions'] = ({login: read(f'the permission of {login}', f'{REPO}/collaborators/{login}/permission',
                                            lambda p: p['permission']) for login in roster}
                               if isinstance(roster, list) else {'unreadable': 'no roster'})
        return snap

    def complete_snapshot(self):
        """The snapshot before write probes: the test fails (nothing sent) unless it was read whole."""
        before = self.snapshot()
        problems = incomplete(before)
        if problems:
            self.fail(f'not exercised: the snapshot before the write probes is incomplete: {problems}')
        return before

    def assert_unchanged(self, before, during):
        after = self.snapshot()
        names = changed(before, after)
        if names:
            RESULTS.append({'action': f'snapshot after {during}', 'expected': 'unchanged', 'status': 'changed',
                            'changed': {k: {'before': before.get(k), 'after': after.get(k)} for k in names}})
            raise SecurityFailure(f'the fixture changed during {during}: {", ".join(names)}')


class NegativeLive(Live):
    PHASE_OF_CLASS = 'negative'

    def refused(self, action, method, path, body=None, headers=None, if_accepted=None):
        """A request the token must not make: 2xx is a SECURITY FAILURE; a refusal must be its scope's 403."""
        status, payload = self.call(action, 'refused by scope (403)', method, path, body, headers,
                                    if_accepted=if_accepted)
        if 200 <= status < 300:
            raise SecurityFailure(f'{action} ({method} {path}) answered {status}')
        self.assertEqual(status, 403, f'{action}: refused with {status}, not by the scope ({message(payload)})')
        return payload

    def sequence(self, probes, send):
        """Send each of PROBES with SEND, in order. A security failure (or the open breaker) stops the sequence at
        once: the probes after it are recorded as not sent and it propagates. Any other failure is collected
        and the sequence goes on; the collected failures are returned."""
        failures = []
        for n, probe in enumerate(probes):
            try:
                send(probe)
            except SecurityFailure:
                BREAKER.withhold(p.action for p in probes[n + 1:])
                raise
            except self.failureException as exc:
                failures.append(str(exc))
        return failures


class TestIdentity(NegativeLive):
    def test_get_token_shows_its_login_and_exact_scope(self):
        status, body = self.call('GET /token', 'allowed', 'GET', '/token')
        self.assertEqual(status, 200)
        self.assertEqual(body['user']['login'], PC.AUDITOR)
        self.assertEqual(sorted(body['scopes']), PC.SCOPES)

    def test_no_password_and_no_more_as_a_password(self):
        for label, password in (('a random password', secrets.token_urlsafe(18)), ('an empty password', '')):
            basic = base64.b64encode(f'{PC.AUDITOR}:{password}'.encode()).decode()
            status = self.http()(self.ctx.port, '/api/v1/repos/search', headers={'Authorization': 'Basic ' + basic})[0]
            RESULTS.append({'action': f'basic authentication with {label}', 'expected': 401, 'status': status})
            self.assertEqual(status, 401)
        basic = base64.b64encode(f'{PC.AUDITOR}:{self.ctx.token}'.encode()).decode()
        for method, path, body in (('GET', '/user', None), ('POST', f'/users/{PC.AUDITOR}/tokens', TOKEN_PROBE_BODY)):
            action = f'{method} {path} with the token as a basic-authentication password'
            if method not in READS:
                BREAKER.check(action)
            status, payload = R.Api(self.ctx.port, http=self.http()).call(method, path, body,
                                                                          {'Authorization': 'Basic ' + basic})
            row = {'action': action, 'expected': 'refused', 'status': status, 'message': message(payload)}
            if method not in READS:
                row['if accepted'] = INVALID.format('name empty: Required; an unknown scope')
            RESULTS.append(row)
            if status == 201 and isinstance(payload, dict) and payload.get('sha1'):
                R.revoke_current(self.ctx.port, payload.pop('sha1'), self.http())  # a last resort, not prevention
            if 200 <= status < 300:
                raise SecurityFailure(f'{method} {path} with the token as a password answered {status}')
            self.assertIn(status, (401, 403))
        del basic


class TestReads(NegativeLive):
    def test_the_auditor_reads_the_rules_and_is_a_repository_administrator(self):
        status, rules = self.call('read the rules', 'allowed', 'GET', f'{REPO}/branch_protections')
        self.assertEqual(status, 200)
        self.assertEqual(sorted(r['rule_name'] for r in rules), sorted(r['rule_name'] for r in R.protection_rules()))
        status, repo = self.call('read the repository', 'allowed', 'GET', REPO)
        self.assertEqual((status, repo['permissions']['admin']), (200, True))

    def test_a_read_collaborator_cannot_read_the_rules(self):
        verifier = R.read_token(self.ctx.provider, 'verifier')
        if verifier is None:
            self.fail('not exercised: no entry for the verifier bot (the control needs a read collaborator)')
        status, payload = self.call('the verifier bot reads the rules (control)', 'refused (reqAdmin)', 'GET',
                                    f'{REPO}/branch_protections', token=verifier)
        self.assertEqual(status, 403, message(payload))


class TestWrites(NegativeLive):
    def test_every_write_is_refused_by_the_scope(self):
        before = self.complete_snapshot()
        try:
            probes = write_probes(before, f'aieh-probe-absent-{secrets.token_hex(4)}')
        except ValueError as exc:
            self.fail(f'not exercised: {exc}')

        def send(probe):
            payload = self.refused(probe.action, probe.method, probe.path, probe.body, if_accepted=probe.if_accepted)
            self.assertIn(SCOPE_REFUSAL, message(payload), probe.action)

        try:
            failures = self.sequence(probes, send)
        finally:
            self.assert_unchanged(before, 'the write probes')
        if failures:
            self.fail('; '.join(failures))

    def test_git_push_through_the_repository_module_is_refused(self):
        RA = _load('repository_access', HERE.parents[1] / 'repository' / 'repository_access.py')
        try:
            RA.dulwich_modules()
        except RA.CannotRun as exc:
            self.fail(f'not exercised: {exc.code} (run under the tools interpreter)')
        before = self.complete_snapshot()
        url = f'http://{G.LOOPBACK}:{self.ctx.port}/{R.FIXTURE_ORG}/{R.FIXTURE_REPO}.git'
        credential = RA.Credential(PC.AUDITOR, self.ctx.token)
        tmp = Path(tempfile.mkdtemp(prefix='aieh-protection-audit-live-'))
        self.addCleanup(shutil.rmtree, tmp, onexc=lambda f, p, e: (os.chmod(p, 0o700), f(p)))
        refs = RA.clone(url, tmp / 'clone.git', credential)
        absent = f'aieh-probe-absent-{secrets.token_hex(8)}'
        if f'refs/heads/work/{absent}' in refs:
            self.fail(f'not exercised: work/{absent} exists')
        from dulwich import objects
        with RA.open_repository(tmp / 'clone.git', config='repository', work_tree=False, ceilings=[tmp]) as repo:
            store = repo._dul.object_store
            blob = objects.Blob.from_string(b'protection auditor probe\n')
            tree = objects.Tree()
            tree.add(b'aieh-audit-probe.txt', 0o100644, blob.id)
            commit = objects.Commit()
            commit.tree, commit.parents = tree.id, []   # no parent: never a fast-forward of main
            commit.author = commit.committer = f'{PC.AUDITOR} <{PC.AUDITOR}@{G.EMAIL_DOMAIN}>'.encode()
            commit.author_time = commit.commit_time = int(time.time())
            commit.author_timezone = commit.commit_timezone = 0
            commit.message = b'protection auditor probe\n'
            for obj in (blob, tree, commit):
                store.add_object(obj)
            try:
                failures = self.sequence(push_probes(commit.id.decode(), absent),
                                         lambda probe: self.push_refused(RA, repo, url, credential, probe))
            finally:
                self.assert_unchanged(before, 'the push probes')
        if failures:
            self.fail('; '.join(failures))

    def push_refused(self, RA, repo, url, credential, probe):
        """One git push the token must not make: PUSH_REFUSED (HTTP 401 or 403 at the receive-pack advertisement)
        passes. A SECURITY FAILURE: a push that succeeds, and PUSH_REJECTED (Gitea served the receive-pack
        advertisement, so the write scope did not refuse the token; the module withheld the update, or Gitea
        rejected it). Any other code fails the test."""
        action, if_accepted = probe.action, probe.if_accepted
        BREAKER.check(action)
        try:
            update = repo.push(url, probe.path, credential)
        except RA.RepositoryError as exc:
            RESULTS.append({'action': action, 'expected': 'PUSH_REFUSED', 'status': exc.code,
                            'message': R.redact(str(exc))[-200:], 'if accepted': if_accepted})
            if exc.code == 'PUSH_REJECTED':
                reason = exc.details.get('reason')
                withheld = reason in ('non-fast-forward', 'remote ref does not exist', 'fetch first')
                raise SecurityFailure(
                    f'{action}: Gitea served the receive-pack advertisement to the read:repository token (its scope '
                    'did not refuse the push); ' + (f'the repository module withheld the update ({reason}): no '
                                                    'update was sent' if withheld else
                                                    f'the update was rejected after the advertisement ({reason})'))
            self.assertEqual(exc.code, 'PUSH_REFUSED', f'{action}: {exc.code}, not refused by the scope')
            return
        RESULTS.append({'action': action, 'expected': 'PUSH_REFUSED', 'status': 'pushed', 'message': str(update),
                        'if accepted': if_accepted})
        raise SecurityFailure(f'{action} with the read:repository token succeeded ({update})')


class TestNoEscape(NegativeLive):
    def test_it_sees_the_fixture_only(self):
        status, found = self.call('GET /repos/search', 'the fixture only', 'GET', '/repos/search?limit=50')
        self.assertEqual(status, 200)
        self.assertEqual([r['full_name'] for r in found['data']], [REPOSITORY])

    def test_user_organization_and_admin_routes_and_sudo(self):
        for action, path, headers in (('GET /user', '/user', None), ('GET /admin/users', '/admin/users', None),
                                      ('GET the organization\'s teams', f'/orgs/{R.FIXTURE_ORG}/teams', None),
                                      ('GET the organization\'s members', f'/orgs/{R.FIXTURE_ORG}/members', None),
                                      ('GET /user/orgs', '/user/orgs', None)):
            with self.subTest(action=action):
                self.refused(action, 'GET', path, headers=headers)
        for target in (G.OWNER, G.SITE_ADMIN):
            with self.subTest(sudo=target):
                status, payload = self.call(f'sudo {target}', 'refused', 'GET', '/token', headers={'Sudo': target})
                self.assertEqual((status, message(payload)), (403, 'Only administrators allowed to sudo.'))

    def test_another_repository_s_rules(self):
        if not OTHER_REPOS:
            self.fail('not exercised: AIEH_PROTECTION_AUDIT_OTHER_REPOS names no repository; unset it to read '
                      f'{ESCAPE_PROBE} (gitea_roles.py escape-probe) or name one the auditor is no collaborator of')
        for other in OTHER_REPOS:
            with self.subTest(repository=other):
                path = f'/repos/{urllib.parse.quote(other)}/branch_protections'
                status, payload = self.call(f'read the rules of {other}', 'refused', 'GET', path)
                if 200 <= status < 300:
                    raise SecurityFailure(f'the auditor read the rules of {other}')
                self.assertIn(status, (403, 404), message(payload))


# ---------------------------------------------------------------- the qualify phase (OA-16 Act D)

QUALIFY_RULE = 'aieh-qualify/*'
BASELINE_VARIABLE = 'AIEH_PROTECTION_AUDIT_BASELINE'
BASELINE = os.environ.get(BASELINE_VARIABLE)
DIGEST = re.compile(r'sha256:[0-9a-f]{64}')


class Injection(NamedTuple):
    label: str
    names: str     # what one of the check's drift problems must contain: the drift identified
    method: str
    path: str
    body: object


def injections() -> list[Injection]:
    """The five drifts the qualify phase injects as the site administrator, in order, each one request."""
    verifier = R.ROLES['verifier']['user']
    return [
        Injection('main.block_admin_merge_override false', 'main.block_admin_merge_override is False', 'PATCH',
                  f'{REPO}/branch_protections/main', {'block_admin_merge_override': False}),
        Injection('main lowered below the catch-all (precedence)', "Gitea enforces the rule '**' on main", 'PATCH',
                  f'{REPO}/branch_protections/main', {'priority': 5}),
        Injection('an extra rule', f"rule '{QUALIFY_RULE}'", 'POST', f'{REPO}/branch_protections',
                  R._total_rule(QUALIFY_RULE, 9)),
        Injection('the verifier bot raised to admin', f'collaborator {verifier}: admin', 'PUT',
                  f'{REPO}/collaborators/{verifier}', {'permission': 'admin'}),
        Injection('squash merges allowed', "the repository's allow_squash_merge is True", 'PATCH', REPO,
                  {'allow_squash_merge': True}),
    ]


def read_back(admin) -> dict:
    """The fixture as the site administrator reads it, independently of the protection check:
    gitea_roles.read_fixture (the settings, each declared collaborator's permission, every rule's 34 fields)
    and the collaborator roster (an undeclared collaborator)."""
    observed = R.read_fixture(admin)
    status, roster = admin.call('GET', f'{REPO}/collaborators?{PC.PAGE}')
    if status != 200 or not isinstance(roster, list) or not all(isinstance(c, dict) for c in roster):
        observed['roster'] = {'unreadable': status, 'message': message(roster)}
    else:
        observed['roster'] = sorted(str(c.get('login')) for c in roster)
    return observed


def _normal_rule(rule) -> dict:
    """A rule's 34 fields, list fields sorted (null equal to []), as the protection check compares them."""
    normal = {}
    for field in R.PROTECTION_FIELDS:
        value = rule.get(field)
        if field in PC.LIST_FIELDS and isinstance(value if value is not None else [], list):
            value = sorted(value or [], key=str)
        normal[field] = value
    return normal


def declaration_differences(observed) -> list[str]:
    """How a read_back differs from the complete declaration (gitea_roles: repository_settings(),
    collaborators(), protection_rules(), every field of every rule); empty when it equals it."""
    differences = []
    full_name = (observed.get('repository') or {}).get('full_name')
    if full_name != REPOSITORY:
        differences.append(f'the repository answers as {full_name!r}, not {REPOSITORY}')
    for key, want in R.repository_settings().items():
        got = observed['settings'].get(key)
        if got != want:
            differences.append(f"the repository's {key} is {got!r}, declared {want!r}")
    declared = R.collaborators()
    for user, want in declared.items():
        got = observed['collaborator_permissions'].get(user)
        if got != want:
            differences.append(f'collaborator {user}: {got!r}, declared {want!r}')
    roster = observed['roster']
    if roster != sorted(declared):
        differences.append(f'the collaborators are {roster!r}, declared {sorted(declared)}')
    rules = observed['branch_protections']
    for name, size in (('the collaborators', len(roster) if isinstance(roster, list) else 0),
                       ('the rules', len(rules))):
        if size >= LIST_LIMIT:
            differences.append(f'{name}: {size} entries, a full page (may be incomplete)')
    want_rules = {r['rule_name']: _normal_rule(r) for r in R.protection_rules()}
    seen = {}
    for rule in rules:
        name = rule.get('rule_name')
        if name in seen:
            differences.append(f'the rule {name!r} is listed twice')
        seen[name] = _normal_rule(rule)
    for name in sorted(set(seen) - set(want_rules), key=str):
        differences.append(f'rule {name!r} is not declared')
    for name in sorted(set(want_rules) - set(seen)):
        differences.append(f'the declared rule {name!r} is missing')
    for name in sorted(set(want_rules) & set(seen)):
        for field in R.PROTECTION_FIELDS:
            if seen[name][field] != want_rules[name][field]:
                differences.append(f'{name}.{field} is {seen[name][field]!r}, declared {want_rules[name][field]!r}')
    return differences


def describe(exc) -> str:
    return f'{type(exc).__name__}: {R.redact(str(exc))[:300]}'


def verdict_row(verdict, baseline=None) -> dict:
    row = {'status': verdict.status, 'code': verdict.code, 'digest': verdict.digest,
           'problems': [R.redact(str(p))[:300] for p in verdict.problems]}
    if baseline is not None:
        row['digest_equals_baseline'] = verdict.digest == baseline
    return row


class QualificationStopped(AssertionError):
    """The qualify phase stopped: a check failed or an outcome was uncertain; no later injection was sent."""


class RestorationFailed(Exception):
    pass


class Recording:
    """The site administrator's API, recording each call it makes (method, path, then status or exception)."""

    def __init__(self, api, log):
        self.api, self.log = api, log

    def call(self, method, path, body=None, headers=None):
        entry = {'method': method, 'path': path}
        self.log.append(entry)
        try:
            status, payload = self.api.call(method, path, body, headers)
        except Exception as exc:
            entry['status'] = 'uncertain: ' + describe(exc)
            raise
        entry['status'] = status
        return status, payload


class Qualification:
    """The qualify phase's sequence (Owner authorization OA-16 Act D), independent of unittest.

    ``run`` checks the baseline precondition, then for each of SCENARIOS in order: checks the stop latch, sends
    the one injection once, requires drift naming it, restores once (the probe rule deleted if present, then one
    gitea_roles.apply_fixture), then requires both an independent read-back as the site administrator equal to
    the complete declaration and a ``verified`` verdict with the baseline digest. After the last it checks the
    complete declaration, the baseline digest, no probe rule and the verifier bot's declared permission.

    Any failed check, non-2xx injection or exception sets the latch (``stopped``) and raises
    QualificationStopped: no later injection is ever sent. A stop after an injection was sent makes one
    restoration attempt for it unless one was already made; then the final state is read once and reported.
    Nothing is retried, and nothing is repaired beyond that one restoration.

    ADMIN: the site administrator's API (``call(method, path, body)``); VERIFY: the protection check, a
    Verdict; TOKEN_VIEW: ``GET /token`` with the auditor's token, (status, payload); BASELINE: the expected
    baseline digest (AIEH_PROTECTION_AUDIT_BASELINE), or None to take the first verdict's; ROWS: the report rows
    (RESULTS by default)."""

    def __init__(self, admin, verify, token_view, baseline=None, rows=None, scenarios=None):
        self.admin, self.verify, self.token_view = admin, verify, token_view
        self.expected_baseline = baseline
        self.rows = RESULTS if rows is None else rows
        self.scenarios = injections() if scenarios is None else list(scenarios)
        self.baseline = None
        self.stopped = None        # the latch: the failed check, once set
        self.sent = []             # the labels of the injections sent
        self.restorations = []     # the labels of the injections a restoration was attempted for

    def run(self):
        self.latch(None)
        self.precondition()
        for scenario in self.scenarios:
            self.scenario(scenario)
        self.final()
        return self.baseline

    def latch(self, scenario):
        if self.stopped is not None:
            raise QualificationStopped(f'the qualification stopped earlier ({self.stopped["check"]}): '
                                       + (f'{scenario.label!r} is not sent' if scenario else 'nothing more runs'))

    def checked(self, row, scenario, check, step):
        """STEP's result; any exception is an uncertain outcome that stops the sequence."""
        try:
            return step()
        except Exception as exc:  # noqa: BLE001 - every failure stops; none is retried
            self.stop(row, scenario, check, f'uncertain outcome: {describe(exc)}')

    def precondition(self):
        """Before any mutation: the auditor's identity and read-only scope, ``verified`` with the expected
        baseline digest, and the read-back equal to the declaration."""
        row = {'action': 'qualify: baseline precondition (no mutation is sent unless it passes)'}
        self.rows.append(row)
        def token_view():
            status, payload = self.token_view()
            return status, payload

        status, body = self.checked(row, None, 'auditor identity', token_view)
        user = body.get('user') if isinstance(body, dict) else None
        login = user.get('login') if isinstance(user, dict) else None
        scopes = body.get('scopes') if isinstance(body, dict) else None
        scopes = sorted(map(str, scopes)) if isinstance(scopes, list) else scopes
        row['auditor'] = {'status': status, 'login': login, 'scopes': scopes}
        if (status, login, scopes) != (200, PC.AUDITOR, PC.SCOPES):
            self.stop(row, None, 'auditor identity', f'GET /token answered {status}, login {login!r}, scopes '
                      f'{scopes!r}; expected 200, {PC.AUDITOR}, exactly {PC.SCOPES}')
        expected = self.expected_baseline
        if expected is not None and not DIGEST.fullmatch(expected):
            self.stop(row, None, 'baseline digest', f'{BASELINE_VARIABLE} is {expected!r}, not sha256:<64 hex>')
        verdict = self.checked(row, None, 'baseline verdict', self.verify)
        row['verdict'] = verdict_row(verdict, expected)
        if verdict.status != 'verified':
            self.stop(row, None, 'baseline verdict', f'the check answered {verdict.status} ({verdict.code}), not '
                      'verified')
        if expected is not None and verdict.digest != expected:
            self.stop(row, None, 'baseline digest', f'the digest {verdict.digest} is not {BASELINE_VARIABLE} '
                      f'{expected}')
        self.baseline = expected or verdict.digest
        row['baseline'] = {'digest': self.baseline,
                           'source': BASELINE_VARIABLE if expected is not None else 'the first verdict'}
        differences = self.checked(row, None, 'baseline read-back',
                                   lambda: declaration_differences(read_back(self.admin)))
        row['read_back'] = differences
        if differences:
            self.stop(row, None, 'baseline read-back', f'the fixture differs from the declaration: {differences}')
        row['result'] = 'passed'

    def scenario(self, scenario):
        self.latch(scenario)
        row = {'action': f'inject: {scenario.label}', 'expected': f'drift naming {scenario.names!r}',
               'injection': {'method': scenario.method, 'path': scenario.path}}
        self.rows.append(row)
        self.sent.append(scenario.label)
        try:
            status, payload = self.admin.call(scenario.method, scenario.path, scenario.body)
        except Exception as exc:  # noqa: BLE001 - sent or not, its outcome is unknown: restore and stop
            row['injection']['status'] = 'uncertain: ' + describe(exc)
            self.stop(row, scenario, 'injection', f'uncertain outcome: the injection raised {describe(exc)}; whether '
                      'Gitea applied it is unknown')
        row['injection'].update(status=status, message=message(payload))
        if not (isinstance(status, int) and 200 <= status < 300):
            self.stop(row, scenario, 'injection', f'the injection answered {status}, not 2xx')
        drift = self.checked(row, scenario, 'drift detection', self.verify)
        row['drift'] = verdict_row(drift)
        if drift.status != 'drift':
            self.stop(row, scenario, 'drift detection', f'the check answered {drift.status} ({drift.code}), not '
                      'drift')
        if not any(scenario.names in str(p) for p in drift.problems):
            self.stop(row, scenario, 'drift detection', f'no drift problem names the injection ({scenario.names!r})')
        failure = self.restore(row, scenario)
        if failure is not None:
            self.stop(row, scenario, 'restoration', failure)
        differences = self.checked(row, scenario, 'read-back',
                                   lambda: declaration_differences(read_back(self.admin)))
        row['read_back'] = differences
        if differences:
            self.stop(row, scenario, 'read-back', f'the fixture differs from the declaration after the restoration: '
                      f'{differences}')
        restored = self.checked(row, scenario, 'restored verdict', self.verify)
        row['verdict'] = verdict_row(restored, self.baseline)
        if (restored.status, restored.digest) != ('verified', self.baseline):
            self.stop(row, scenario, 'restored verdict', f'the check answered {restored.status} ({restored.code}) '
                      f'with digest {restored.digest}, not verified with the baseline {self.baseline}')
        row['result'] = 'passed'

    def restore(self, row, scenario):
        """One bounded restoration for SCENARIO: delete the probe rule if present, then one apply_fixture. The
        first failure ends it; nothing is retried. None, or what failed."""
        self.restorations.append(scenario.label)
        api = Recording(self.admin, row.setdefault('restoration', []))
        try:
            status, rules = api.call('GET', f'{REPO}/branch_protections')
            if status != 200 or not isinstance(rules, list):
                raise RestorationFailed(f'GET the rules answered {status}')
            if QUALIFY_RULE in {r.get('rule_name') for r in rules if isinstance(r, dict)}:
                status, payload = api.call('DELETE',
                                           f'{REPO}/branch_protections/{urllib.parse.quote(QUALIFY_RULE, safe="")}')
                if status not in (200, 204):
                    raise RestorationFailed(f'DELETE the rule {QUALIFY_RULE!r} answered {status} ({message(payload)})')
            R.apply_fixture(api)
        except Exception as exc:  # noqa: BLE001 - a restoration that fails is reported, never retried
            row['restoration_failed'] = describe(exc)
            return f'the restoration failed: {describe(exc)}'
        return None

    def final(self):
        """After the last injection: the complete declaration, the baseline digest, no probe rule, the verifier
        bot's declared permission."""
        row = {'action': 'qualify: after the last injection'}
        self.rows.append(row)
        observed = self.checked(row, None, 'final read-back', lambda: read_back(self.admin))
        differences = self.checked(row, None, 'final read-back', lambda: declaration_differences(observed))
        verifier = R.ROLES['verifier']['user']
        rules = [r.get('rule_name') for r in observed['branch_protections']]
        permission = observed['collaborator_permissions'].get(verifier)
        row.update(read_back=differences, probe_rule_present=QUALIFY_RULE in rules, verifier_permission=permission)
        if differences or QUALIFY_RULE in rules or permission != R.ROLES['verifier']['permission']:
            self.stop(row, None, 'final read-back', f'differences {differences}; the rule {QUALIFY_RULE!r} '
                      f'{"present" if QUALIFY_RULE in rules else "absent"}; {verifier}: {permission!r}')
        verdict = self.checked(row, None, 'final verdict', self.verify)
        row['verdict'] = verdict_row(verdict, self.baseline)
        if (verdict.status, verdict.digest) != ('verified', self.baseline):
            self.stop(row, None, 'final verdict', f'the check answered {verdict.status} ({verdict.code}) with digest '
                      f'{verdict.digest}, not verified with the baseline {self.baseline}')
        row['result'] = 'passed'

    def stop(self, row, scenario, check, detail):
        """Set the latch, make the one restoration attempt still owed, read the final state once, report, and
        raise QualificationStopped."""
        self.stopped = {'check': check, 'scenario': scenario.label if scenario else None, 'detail': detail}
        row['result'] = f'stopped: {check}'
        report = {'action': 'qualify: STOPPED', 'failed_check': check,
                  'scenario': scenario.label if scenario else None, 'detail': detail}
        if scenario is None or scenario.label not in self.sent:
            report['restoration_after_stop'] = 'none owed: no injection of this step was sent'
        elif scenario.label in self.restorations:
            report['restoration_after_stop'] = 'not attempted again: its one restoration was already attempted'
        else:
            failure = self.restore(row, scenario)
            report['restoration_after_stop'] = failure or 'attempted once and completed (final state below)'
        state = {}
        try:
            state['read_back'] = declaration_differences(read_back(self.admin))
        except Exception as exc:  # noqa: BLE001 - reported, not retried
            state['read_back'] = 'unreadable: ' + describe(exc)
        try:
            state['verdict'] = verdict_row(self.verify(), self.baseline)
        except Exception as exc:  # noqa: BLE001
            state['verdict'] = 'unverifiable: ' + describe(exc)
        report['final_state'] = state
        report['not_sent'] = [s.label for s in self.scenarios if s.label not in self.sent]
        self.rows.append(report)
        for label in report['not_sent']:
            self.rows.append({'action': f'inject: {label}', 'status': 'not sent',
                              'message': f'the qualification stopped earlier ({check}); this injection was not sent'})
        raise QualificationStopped(f'the qualify phase STOPPED at {check}'
                                   + (f' ({scenario.label})' if scenario else '') + f': {detail}. Restoration after '
                                   f'the stop: {report["restoration_after_stop"]}. Final state: {state}. Not sent: '
                                   f'{report["not_sent"]}. Not a PASS; report the observed state.')


class QualifyLive(Live):
    """The verifier qualification: drift injected as the site administrator is detected, then restored."""
    PHASE_OF_CLASS = 'qualify'

    def verify(self):
        return PC.verify(self.ctx.provider, self.ctx.port, REPOSITORY, R.DEFAULT_BRANCH,
                         http=getattr(self.ctx, 'http', None))

    def test_injected_drift_is_detected_and_restored(self):
        admin = R.admin_api(self.ctx.provider, self.ctx.port, getattr(self.ctx, 'http', None))
        auditor = R.Api(self.ctx.port, self.ctx.token, self.http())
        Qualification(admin, self.verify, lambda: auditor.call('GET', '/token'), BASELINE).run()


if __name__ == '__main__':
    unittest.main()
