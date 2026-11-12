"""The write safety of the live authorization and transport suites, offline (Owner authorization OA-16 Act C).

``test_authorization_live.py`` (``task gitea:authz``) and ``test_transport_live.py`` (``task gitea:transport``)
are run here through unittest, as the live runs would be, against fakes; nothing reaches a real Gitea or
Credential Manager:

- ``MatrixGitea``, a fake Gitea 28.3.0 API (called in memory with gitea_host.http_get's signature) answering
  the five role bots as S-01.2.2 observed: token scopes (``tokenRequiresScopes``: the category from the
  route, the level from the method), ``sudo``, the fixture's reads, builder's and planner's proposal PRs,
  the reviewer's review, merges refused (405) and other repository writes refused by permission (403). A
  role in ``broken`` gets its writes past a broken scope check: ``accept`` answers each 201 (and the sign-in
  form 303), ``validate`` applies Gitea's body binding and handlers as modelled here (``Required`` fields, an
  unknown token scope, the reserved secret prefix ``GITEA_``, an absent repository, user, organization or
  token: 404) and records whatever a write would have created or changed;
- ``FakeGit`` for the git suite's ``git`` (each role's push as Gitea answers it: 403 at the receive-pack
  advertisement for a read-only token, the pre-receive hook declining what a writer may not push);
- ``GiteaGit``, a smart-HTTP server on 127.0.0.1 (Dulwich's ``dulwich.web``) serving the fixture as Gitea
  answers the roles, for the transport suite's repository module and for real ``git push --dry-run`` runs
  of the auditor's pushes.

Covered: both modules skip without their opt-ins and read no credential; the shared breaker; in each module
the breaker tripped by any role's unexpected acceptance (a write answered 2xx, a sign-in not refused, a push
that succeeds, main moving, the auditor's advertisement served) stops every later write of every role,
counted at the fakes, despite ``subTest``, and ``tearDownModule`` fails the run naming the probe; the
protection auditor's writes refused by the scope pass, are sent to absent targets or with bodies the
modelled validation rejects, and create or change nothing past a broken scope, while the bodies they used
before would have; the unexercised ones are reported and fail "not exercised"; its git pushes (real git,
``--dry-run``) and module pushes are refused at the advertisement and, if served, send no update; and the
other roles' requests are those of commit 7995a75, compared with ``live_matrix_7995a75.json`` (recorded by
running these harnesses over that commit's two modules: ``record_golden``). Every value is synthetic.
"""
from __future__ import annotations

import base64
import contextlib
import copy
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer

CATEGORY = 'unit'

HERE = Path(__file__).resolve().parent


def _load(name, path):
    if (module := sys.modules.get(name)) is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = sys.modules[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


A = _load('test_authorization_live', HERE / 'test_authorization_live.py')
T = _load('test_transport_live', HERE / 'test_transport_live.py')
LB = _load('aieh_gitea_live_breaker', HERE / 'live_breaker.py')
PF = _load('aieh_gitea_protection_fake', HERE / 'protection_fake.py')
RA = _load('repository_access', HERE.parents[1] / 'repository' / 'repository_access.py')
R, G = A.R, A.G
AUDITOR = 'protection-audit'
PROPOSERS = ('builder', 'planner')
READS = ('GET', 'HEAD')
FIXTURE = f'/repos/{R.FIXTURE_ORG}/{R.FIXTURE_REPO}'
GOLDEN = HERE / 'live_matrix_7995a75.json'
AUTHZ_CLASSES = ('TestTokens', 'TestInstanceWideDenials', 'TestFixtureAllowed', 'TestFixtureDenied')
TOKENS = {role: PF.synthetic_token(spec['user']) for role, spec in R.ROLES.items()}
TOKEN_ROLE = {token: role for role, token in TOKENS.items()}
USER_ROLE = {spec['user']: role for role, spec in R.ROLES.items()}
SCOPE_TEXT = 'token does not have at least one of required scope(s), required=[{required}], token scope={scope}'
ADMIN_TEXT = 'user should be an owner or a collaborator with admin write of a repository'
GIT_403 = (b"fatal: unable to access 'http://127.0.0.1:3000/aieh-authz-fixture/authz.git/': The requested URL "
           b'returned error: 403\n')
DECLINED = b' ! [remote rejected] HEAD -> main (pre-receive hook declined)\nerror: failed to push some refs\n'


class Deterministic:
    """The live modules' ``secrets``, fixed, so that two runs send the same requests."""

    @staticmethod
    def token_urlsafe(n=None):
        return 'a' * 24

    @staticmethod
    def token_hex(n=None):
        return '0' * (2 * (n or 32))


# ---------------------------------------------------------------- the fake Gitea API


def category(route):
    for prefix, name in (('/repos', 'repository'), ('/user', 'user'), ('/users', 'user'), ('/admin', 'admin'),
                         ('/orgs', 'organization')):
        if route == prefix or route.startswith(prefix + '/'):
            return name
    return None


def has_scope(scopes, level, cat):
    return 'all' in scopes or f'{level}:{cat}' in scopes or (level == 'read' and f'write:{cat}' in scopes)


class MatrixGitea:
    """The fake Gitea 28.3.0 API of the module docstring. ``log`` (shared with ``FakeGit``) receives every
    request in order: role, method, path, body (text) and the status answered."""

    def __init__(self, broken=(), mode='gitea', log=None):
        self.broken, self.mode = set(broken), mode
        self.log = [] if log is None else log
        self.created, self.changed = [], []
        self.pulls, self.branches = {}, {R.DEFAULT_BRANCH: 'c' * 40}
        self.users = {spec['user'] for spec in R.ROLES.values()} | {G.OWNER, G.SITE_ADMIN}
        self.owner_tokens = {'1': 'aieh-owner-token'}
        self.lock = threading.Lock()

    @property
    def requests(self):
        return [entry for entry in self.log if entry['kind'] == 'http']

    def writes(self, role=None):
        return [r for r in self.requests if r['method'] not in READS and (role is None or r['role'] == role)]

    def state(self):
        return copy.deepcopy((self.created, self.changed, self.branches, self.owner_tokens))

    def __call__(self, port, path, *, method='GET', body=None, headers=None, timeout=5.0):
        with self.lock:
            entry = {'kind': 'http', 'role': None, 'method': method, 'path': path,
                     'body': None if body is None else body.decode('utf-8')}
            self.log.append(entry)
            lowered = {k.lower(): v for k, v in (headers or {}).items()}
            status, payload, extra = self._handle(entry, method, path, lowered, body)
            entry['status'] = status
            data = payload if isinstance(payload, bytes) else b'' if payload is None else json.dumps(payload).encode()
            return status, {'content-type': 'application/json', **extra}, data

    def _handle(self, entry, method, path, headers, body):
        if path == '/user/login':
            form = dict(urllib.parse.parse_qsl(body.decode('utf-8')))
            entry['role'] = USER_ROLE.get(form.get('user_name'), 'anonymous')
            if entry['role'] in self.broken and self.mode == 'accept':
                return 303, None, {'location': '/'}
            return 200, b'<html>Username or password is incorrect.</html>', {}
        parsed = urllib.parse.urlsplit(path)
        route, query = parsed.path.removeprefix('/api/v1'), dict(urllib.parse.parse_qsl(parsed.query))
        auth = headers.get('authorization', '')
        role = None
        if auth.startswith('token '):
            role = TOKEN_ROLE.get(auth[6:])
        elif auth.startswith('Basic '):
            user, _, password = base64.b64decode(auth[6:]).decode('utf-8').partition(':')
            candidate = USER_ROLE.get(user)
            entry['role'] = candidate or 'anonymous'
            role = candidate if candidate and password == TOKENS[candidate] else None
        entry['role'] = role or entry['role'] or 'anonymous'
        if role is None:
            return 401, {'message': 'token is required'}, {}
        if 'sudo' in headers or 'sudo' in query:
            return 403, {'message': PF.SUDO_TEXT}, {}
        write = method not in READS
        data = json.loads(body) if body else None
        if write and role in self.broken:
            return (*self.past_the_scope(role, method, route, data if isinstance(data, dict) else {}), {})
        scopes = R.ROLES[role]['scopes']
        cat = category(route)
        level = 'write' if write else 'read'
        if route not in ('/token',) and cat and not has_scope(scopes, level, cat):
            return 403, {'message': SCOPE_TEXT.format(required=f'{level}:{cat}', scope=','.join(scopes))}, {}
        if route == '/token':
            if method == 'DELETE':
                return 204, None, {}
            return 200, {'id': 7, 'name': f'aieh-{role}-x', 'scopes': list(scopes),
                         'user': {'login': R.ROLES[role]['user']}}, {}
        if not (route == FIXTURE or route.startswith(FIXTURE + '/')):
            return 404, {'message': 'not found'}, {}
        return (*self.fixture(role, method, route[len(FIXTURE):], data, query), {})

    def fixture(self, role, method, rest, data, query):
        if method == 'GET':
            if rest == '':
                return 200, {'full_name': FIXTURE[7:], 'private': True}
            if rest.startswith('/branches/'):
                name = urllib.parse.unquote(rest[len('/branches/'):])
                if name not in self.branches:
                    return 404, {'message': 'branch not found'}
                return 200, {'name': name, 'commit': {'id': self.branches[name]}, 'protected': name == 'main'}
            if rest == '/pulls':
                return 200, [{'number': n, 'head': {'ref': p['head']}} for n, p in self.pulls.items() if p['open']]
            if (match := re.fullmatch(r'/pulls/(\d+)', rest)) and int(match[1]) in self.pulls:
                return 200, {'number': int(match[1]), 'merged': self.pulls[int(match[1])]['merged'], 'merged_by': None}
            if rest.startswith('/raw/'):
                return 200, b'fixture\n'
            if rest.startswith('/actions/'):
                return 403, {'message': 'user should be the owner of the repo'}
            return 404, {'message': 'not found'}
        if method == 'POST' and rest == '/pulls' and role in PROPOSERS:
            number = len(self.pulls) + 1
            self.pulls[number] = {'head': data['head'], 'open': True, 'merged': False, 'by': role}
            return 201, {'number': number}
        if method == 'POST' and re.fullmatch(r'/pulls/\d+/reviews', rest) and role == 'reviewer':
            return 200, {'id': 1}
        if method == 'PATCH' and (match := re.fullmatch(r'/pulls/(\d+)', rest)):
            self.pulls[int(match[1])]['open'] = False
            return 201, {'number': int(match[1])}
        if method == 'POST' and re.fullmatch(r'/pulls/\d+/merge', rest):
            return 405, {'message': 'User not allowed to merge PR'}
        return 403, {'message': ADMIN_TEXT}

    # ------------------------------------------------------------ past a broken scope check

    def past_the_scope(self, role, method, route, body):
        if self.mode == 'accept':
            self.created.append((role, method, route))
            return 201, {'id': 99, 'number': 99}
        return self.validate(method, route, body)

    def create(self, kind, route, payload=None):
        self.created.append((kind, route))
        return 201, payload or {'id': 99}

    def change(self, what, route, status=200):
        self.changed.append((what, route))
        return status, None

    def validate(self, method, route, body):
        """Gitea 28.3.0's answer to a write past the scope check as modelled here: the body binding (422, or
        400 for an unknown token scope or a reserved secret name), then the handler (404 for an absent
        repository, user, organization or token; otherwise the write is applied and recorded)."""
        def required(*fields):
            missing = [f for f in fields if not body.get(f)]
            return (422, {'message': f'[{", ".join(missing)}]: Required'}) if missing else None

        def match(pattern):
            return re.fullmatch(pattern, route)

        if method == 'POST' and route == '/admin/actions/runners/registration-token':
            return self.create('runner registration token', route)
        if method == 'POST' and route == '/admin/users':
            return required('username', 'email') or self.create('user', route)
        if (m := match(r'/admin/users/([^/]+)')) and method == 'PATCH':
            return (404, {'message': 'user does not exist'}) if m[1] not in self.users else self.change('user', route)
        if (m := match(r'/admin/users/([^/]+)/orgs')) and method == 'POST':
            if m[1] not in self.users:
                return 404, {'message': 'user does not exist'}
            return required('username') or self.create('organization', route)
        if method == 'POST' and route == '/orgs':
            return required('username') or self.create('organization', route)
        if method == 'POST' and (route == '/user/repos' or match(r'/orgs/[^/]+/repos')):
            if route != '/user/repos' and route.split('/')[2] != R.FIXTURE_ORG:
                return 404, {'message': 'organization does not exist'}
            return required('name') or self.create('repository', route)
        if (m := match(r'/users/([^/]+)/tokens')) and method == 'POST':
            if m[1] not in self.users:
                return 404, {'message': 'user does not exist'}
            if failed := required('name'):
                return failed
            if not body.get('scopes') or any(s not in PF_SCOPES for s in body['scopes']):
                return 400, {'message': 'invalid access token scope'}
            return self.create('token', route, {'id': 11, 'name': body['name'], 'sha1': 'e' * 40})
        if (m := match(r'/users/([^/]+)/tokens/([^/]+)')) and method == 'DELETE':
            if m[1] != G.OWNER or m[2] not in self.owner_tokens:
                return 404, {'message': 'token does not exist'}
            del self.owner_tokens[m[2]]
            return self.change('token deleted', route, 204)
        if (m := match(r'/user/actions/secrets/([^/]+)')) and method == 'PUT':
            if failed := required('data'):
                return failed
            if re.match(r'(?i)GIT(EA|HUB)_', m[1]):
                return 400, {'message': 'invalid secret name'}
            return self.create('secret', route)
        if route.startswith('/repos/'):
            if not (route == FIXTURE or route.startswith(FIXTURE + '/')):
                return 404, {'message': 'repository does not exist'}
            return self.change('the fixture', f'{method} {route}', 204 if method == 'DELETE' else 200)
        return 404, {'message': f'no route {method} {route}'}


PF_SCOPES = {f'{level}:{cat}' for level in ('read', 'write')
             for cat in ('activitypub', 'admin', 'issue', 'misc', 'notification', 'organization', 'package',
                         'repository', 'user')} | {'all', 'public-only'}


def normalize_arg(arg):
    return re.sub(r'^.*aieh-authz-[^\\/]+', '<tmp>', arg).replace(chr(92), '/')


class FakeGit:
    """The git suite's ``git(ctx, role, *args, cwd)``: each push answered as Gitea answers the role (403 at the
    advertisement for a read-only token, the hook declining what a writer may not push); a role in ACCEPT
    has every push done; ON_PUSH(role, args) runs on each push."""

    def __init__(self, log, accept=(), on_push=None):
        self.log, self.accept, self.on_push = log, set(accept), on_push

    def pushes(self, role=None):
        return [e for e in self.log if e['kind'] == 'git' and e['args'][0] == 'push'
                and (role is None or e['role'] == role)]

    def __call__(self, ctx, role, *args, cwd):
        self.log.append({'kind': 'git', 'role': role, 'args': [normalize_arg(a) for a in args]})
        code, out, err = 0, b'', b''
        if args[0] == 'clone':
            Path(args[-1]).mkdir(parents=True, exist_ok=True)
        elif args[0] == 'commit-tree':
            out = b'f' * 40 + b'\n'
        elif args[0] == 'push':
            if self.on_push is not None:
                self.on_push(role, args)
            dst = args[-1].split(':', 1)[1]
            if role in self.accept:
                code = 0
            elif 'write:repository' not in R.ROLES[role]['scopes']:
                code, err = 128, GIT_403
            elif not (role in PROPOSERS and dst == f'refs/heads/work/authz-{role}'):
                code, err = 1, DECLINED
        return subprocess.CompletedProcess(['git', *args], code, out, err)


def run_suite(module, classes, patches):
    """Run CLASSES of MODULE as unittest would (class and module fixtures, subTest), under PATCHES."""
    loader = unittest.TestLoader()
    result = unittest.TestResult()
    with contextlib.ExitStack() as stack:
        for patch in patches:
            stack.enter_context(patch)
        unittest.TestSuite([loader.loadTestsFromTestCase(getattr(module, name)) for name in classes]).run(result)
    for name in classes:
        tmp = vars(getattr(module, name)).get('tmp')
        if tmp is not None and tmp.exists():   # left by a class whose setUpClass failed (7995a75's tearDownClass)
            shutil.rmtree(tmp, onexc=lambda f, p, e: (os.chmod(p, 0o700), f(p)))
        for attr in ('ctx', 'tmp', 'url', 'clones', 'pulls', 'pushes', 'credentials', 'launched'):
            if attr in vars(getattr(module, name)):
                delattr(getattr(module, name), attr)
    return result


def authz_run(fake, git, module=None, classes=AUTHZ_CLASSES):
    """(unittest result, report rows, breaker) of the git suite's CLASSES against FAKE and GIT."""
    module = module or A
    users = {spec['user']: {'admin': False, 'type': 'Bot'} for spec in R.ROLES.values()}
    ctx = SimpleNamespace(port=3000, tokens=dict(TOKENS), cli=SimpleNamespace(users=lambda: users))
    rows = []
    breaker = LB.Breaker(rows.append)
    patches = [mock.patch.object(module, '_LIVE', [(ctx, None)]), mock.patch.object(module, 'RESULTS', rows),
               mock.patch.object(module, 'REPORT', None), mock.patch.object(G, 'http_get', fake),
               mock.patch.object(module, 'git', git), mock.patch.object(module, 'secrets', Deterministic)]
    if hasattr(module, 'BREAKER'):
        patches.append(mock.patch.object(module, 'BREAKER', breaker))
    return run_suite(module, classes, patches), rows, breaker


def others(log):
    """The other roles' requests: every write (HTTP method, path and body; git argv), in order."""
    out = []
    for e in log:
        if e['role'] == AUDITOR:
            continue
        if e['kind'] == 'http' and e['method'] not in READS:
            out.append(['http', e['role'], e['method'], e['path'], e['body']])
        elif e['kind'] == 'git':
            out.append(['git', e['role'], *e['args']])
    return out


def authz_log(module=None):
    log = []
    authz_run(MatrixGitea(log=log), FakeGit(log), module)
    return others(log)


def failures_of(result):
    return [(str(test), text.strip().splitlines()[-1]) for test, text in result.failures + result.errors]


# ---------------------------------------------------------------- a smart-HTTP Gitea for git


class Quiet(WSGIRequestHandler):
    def log_message(self, *_args):
        pass


def pkt_commands(data):
    """The update commands of a receive-pack request body (its pkt-lines before the first flush)."""
    commands, i = [], 0
    while i + 4 <= len(data):
        length = int(data[i:i + 4], 16)
        if length == 0:
            break
        commands.append(data[i + 4:i + length].split(b'\0')[0].strip().decode())
        i += length
    return commands


class GiteaGit:
    """Smart HTTP on 127.0.0.1 serving the fixture (main: one commit) at /aieh-authz-fixture/authz.git as Gitea
    answers the bots: a read-only token gets 403 at receive-pack (advertisement and update), unless in
    ``serve``; a writer's update is declined by the hook (pre-receive) except its own work/authz-<role>
    branch for builder and planner; a role in ``accept`` has every update applied; no credential: 401.
    ``requests``: role, method, path, query and the update commands of each request."""

    def __init__(self):
        RA.dulwich_modules()
        from dulwich import errors, objects, repo, server, web
        from dulwich.config import StackedConfig
        self.repo = r = repo.MemoryRepo()
        r.get_config_stack = lambda: StackedConfig([r.get_config()])
        blob = objects.Blob.from_string(b'fixture\n')
        tree = objects.Tree()
        tree.add(b'README.md', 0o100644, blob.id)
        commit = objects.Commit()
        commit.tree, commit.parents = tree.id, []
        commit.author = commit.committer = b'Fixture <fixture@example.invalid>'
        commit.author_time = commit.commit_time = 1762992000
        commit.author_timezone = commit.commit_timezone = 0
        commit.message = b'fixture\n'
        for obj in (blob, tree, commit):
            r.object_store.add_object(obj)
        self.main = commit.id
        self.requests, self.serve, self.accept, self.role = [], set(), set(), None
        self.reset()
        outer = self

        class Hook:
            def execute(self, ref, old, new):
                role = outer.role
                if role in outer.accept or (role in PROPOSERS and ref == f'refs/heads/work/authz-{role}'.encode()):
                    return b'', b''
                if role == outer.move_main and ref == b'refs/heads/main':   # main moves, yet the push is declined
                    outer.repo.refs[b'refs/heads/main'] = new
                raise errors.HookError('pre-receive hook declined')

        r.hooks = {'update': Hook()}
        app = web.make_wsgi_chain(server.DictBackend({f'{FIXTURE[6:]}.git': r}))
        credentials = {}
        for role, spec in R.ROLES.items():
            for scheme in ('basic', 'token'):
                credentials[RA.Credential(spec['user'], TOKENS[role], scheme=scheme).authorization()] = role

        def authorizing(environ, start_response):
            role = credentials.get(environ.get('HTTP_AUTHORIZATION'))
            where = environ['PATH_INFO'] + '?' + environ.get('QUERY_STRING', '')
            commands = []
            if environ['REQUEST_METHOD'] == 'POST' and 'git-receive-pack' in where and environ.get('CONTENT_LENGTH'):
                data = environ['wsgi.input'].read(int(environ['CONTENT_LENGTH']))
                environ['wsgi.input'] = io.BytesIO(data)
                commands = pkt_commands(data)
            self.requests.append({'role': role or 'anonymous', 'method': environ['REQUEST_METHOD'],
                                  'path': environ['PATH_INFO'], 'query': environ.get('QUERY_STRING', ''),
                                  'commands': commands})
            if role is None:
                start_response('401 Unauthorized', [('WWW-Authenticate', 'Basic realm="test"')])
                return [b'authentication required\n']
            if ('git-receive-pack' in where and 'write:repository' not in R.ROLES[role]['scopes']
                    and role not in self.serve):
                start_response('403 Forbidden', [('Content-Type', 'text/plain')])
                return [b'token does not have at least one of required scope(s)\n']
            self.role = role
            return app(environ, start_response)

        self.httpd = WSGIServer(('127.0.0.1', 0), Quiet)
        self.httpd.set_app(authorizing)
        self.port = self.httpd.server_address[1]
        self.url = f'http://127.0.0.1:{self.port}/{R.FIXTURE_ORG}/{R.FIXTURE_REPO}.git'
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
        self.thread.start()

    def reset(self):
        for ref in list(self.repo.get_refs()):
            if ref != b'HEAD':
                del self.repo.refs[ref]
        self.repo.refs[b'refs/heads/main'] = self.main
        self.repo.refs.set_symbolic_ref(b'HEAD', b'refs/heads/main')
        self.requests.clear()
        self.serve, self.accept, self.move_main = set(), set(), None

    def refs(self):
        return {k.decode(): v.decode() for k, v in self.repo.get_refs().items() if k != b'HEAD'}

    def receive_pack(self, role=None):
        return [r for r in self.requests if 'git-receive-pack' in r['path'] + r['query']
                and (role is None or r['role'] == role)]

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()
        self.repo.close()


class GitApi:
    """gitea_host.http_get for the suites' API reads next to GiteaGit: the fixture (200), its branches (from
    the server's refs, 404 when absent); writes answered as MatrixGitea's scope rule does (403)."""

    def __init__(self, server):
        self.server, self.requests = server, []

    def __call__(self, port, path, *, method='GET', body=None, headers=None, timeout=5.0):
        route = urllib.parse.urlsplit(path).path.removeprefix('/api/v1')
        self.requests.append((method, route))
        if method not in READS:
            return 403, {}, json.dumps({'message': SCOPE_TEXT.format(required='write:repository',
                                                                     scope='read:repository')}).encode()
        if route == FIXTURE:
            return 200, {}, b'{"private": true}'
        if route.startswith(FIXTURE + '/branches/'):
            sha = self.server.refs().get('refs/heads/' + urllib.parse.unquote(route[len(FIXTURE + '/branches/'):]))
            return (200, {}, json.dumps({'commit': {'id': sha}}).encode()) if sha else (404, {}, b'{}')
        return 404, {}, b'{}'


def transport_run(server, module=None):
    """(unittest result, report rows, breaker) of the transport suite's matrix against SERVER."""
    module = module or T
    ctx = SimpleNamespace(port=server.port, tokens=dict(TOKENS))
    rows = []
    breaker = LB.Breaker(rows.append)
    patches = [mock.patch.object(module, '_LIVE', [(ctx, None)]), mock.patch.object(module, 'RESULTS', rows),
               mock.patch.object(module, 'REPORT', None), mock.patch.object(G, 'http_get', GitApi(server))]
    if hasattr(module, 'BREAKER'):
        patches.append(mock.patch.object(module, 'BREAKER', breaker))
    return run_suite(module, ('TestMatrix',), patches), rows, breaker


def transport_others(requests):
    """The other roles' requests at the git server, in order, object names numbered by first appearance."""
    names = {}

    def number(match):
        return names.setdefault(match[0], f'<{len(names) + 1}>') if match[0] != '0' * 40 else '<zero>'

    return [[r['role'], r['method'], r['path'], r['query'], [re.sub(r'[0-9a-f]{40}', number, c) for c in r['commands']]]
            for r in requests if r['role'] != AUDITOR]


def transport_log(module=None):
    server = GiteaGit()
    try:
        transport_run(server, module)
        return transport_others(server.requests)
    finally:
        server.close()


def record_golden(authz_module, transport_module, out=GOLDEN):
    """Write the other roles' requests of the two given modules (those of commit 7995a75) to OUT."""
    how = ('test_live_matrix_safety.record_golden over the two modules of git show 7995a75, loaded under their own '
           'module names after gitea_host, gitea_roles and repository_access of the working tree')

    def entries(log):
        return '[\n' + ',\n'.join('  ' + json.dumps(entry) for entry in log) + '\n ]'
    text = (f'{{\n "recorded_from": "7995a75",\n "how": {json.dumps(how)},\n'
            f' "authorization": {entries(authz_log(authz_module))},\n'
            f' "transport": {entries(transport_log(transport_module))}\n}}\n')
    json.loads(text)
    Path(out).write_text(text, encoding='utf-8', newline='\n')


# ---------------------------------------------------------------- the tests


class Skips(unittest.TestCase):
    def test_both_modules_skip_without_their_opt_ins_and_read_no_credential(self):
        with mock.patch.object(G, 'credential_provider', side_effect=AssertionError('read Credential Manager')):
            for module, flag, names in ((A, 'AIEH_GITEA_AUTHZ', AUTHZ_CLASSES), (T, 'AIEH_GITEA_TRANSPORT',
                                                                                   ('TestMatrix', 'TestClone'))):
                with mock.patch.object(module, 'OPT_IN', False), mock.patch.object(module, '_LIVE', []):
                    for name in names:
                        with self.subTest(cls=name), self.assertRaises(unittest.SkipTest) as caught:
                            getattr(module, name).setUpClass()
                        self.assertIn(f'opt-in: {flag}=1', str(caught.exception))


class SharedBreaker(unittest.TestCase):
    def test_trip_check_withhold_and_sequence(self):
        rows = []
        breaker = LB.Breaker(rows.append)
        breaker.check('a write')   # not tripped: nothing
        self.assertIsInstance(breaker.fail('first'), LB.SecurityFailure)
        breaker.fail('second')
        self.assertEqual(breaker.tripped_by, 'first')
        with self.assertRaises(LB.BreakerOpen):
            breaker.check('a later write')
        self.assertEqual(breaker.withheld, ['a later write'])
        self.assertEqual(rows[-1]['status'], 'not sent')

        fresh, sent = LB.Breaker(rows.append), []
        probes = [LB.Probe('one', 'POST', '/a'), LB.Probe('two', 'POST', '/b'), LB.Probe('skipped', None, None),
                  LB.Probe('three', 'PUSH', ':refs/heads/x')]

        def send(probe):
            sent.append(probe.action)
            if probe.action == 'one':
                raise AssertionError('an ordinary failure')
            if probe.action == 'two':
                raise fresh.fail('two answered 201')
        with self.assertRaises(LB.SecurityFailure):
            LB.sequence(fresh, probes, send)
        self.assertEqual(sent, ['one', 'two'])
        self.assertEqual(fresh.withheld, ['three'])   # the unexercised one is not a withheld write

    def test_close_run(self):
        rows = [{'action': 'x'}]
        LB.Breaker(rows.append).close_run(rows, None)   # not tripped: nothing raised
        breaker = LB.Breaker(rows.append)
        breaker.fail('POST /x answered 201')
        breaker.withhold(['later'])
        with mock.patch.object(LB.Path, 'write_text') as write, self.assertRaises(AssertionError) as caught:
            breaker.close_run(rows, 'report.json')
        self.assertIn('SECURITY FAILURE in this run: the circuit breaker tripped at POST /x answered 201',
                      str(caught.exception))
        written = json.loads(write.call_args[0][0])
        self.assertEqual(written[-1], {'action': 'circuit breaker', 'tripped_by': 'POST /x answered 201',
                                       'not_sent': ['later']})


class AuthorizationRuns(unittest.TestCase):
    """The git suite run whole against the fakes (class fixtures make temporary clone directories)."""
    category = 'contract'

    def test_every_auditor_write_is_refused_by_its_scope_and_two_are_not_exercised(self):
        log = []
        fake, git = MatrixGitea(log=log), FakeGit(log)
        result, rows, breaker = authz_run(fake, git)
        self.assertIsNone(breaker.tripped_by)
        self.assertEqual(result.errors, [])
        failed = failures_of(result)
        self.assertEqual(sorted(t.split(' ')[0] for t, _m in failed), ['test_admin_endpoints',
                                                                       'test_no_interactive_sign_in'])
        for test, text in failed:
            self.assertIn("role='protection-audit'", test)
            self.assertIn('not exercised', text)
            self.assertIn(A.COVERED, text)
        unexercised = [r for r in rows if r['status'] == 'UNEXERCISED']
        self.assertEqual([r['action'] for r in unexercised], ['web sign-in form with a random password',
                                                              'POST /admin/actions/runners/registration-token'])
        audited = fake.writes(AUDITOR)
        self.assertEqual(len(audited), 29)
        self.assertTrue(all(w['status'] == 403 for w in audited), audited)
        self.assertFalse([w for w in audited if w['path'].startswith('/api/v1' + FIXTURE)])   # never the fixture
        self.assertFalse([w for w in fake.requests if w['role'] == AUDITOR and w['path'] in (
            '/user/login', '/api/v1/admin/actions/runners/registration-token')])
        pushes = git.pushes(AUDITOR)
        self.assertEqual([p['args'][:3] for p in pushes], [['push', '--dry-run', 'origin']] * 4)
        self.assertEqual([p['args'][3] for p in pushes], ['f' * 40 + ':refs/heads/main',
                                                          '+:refs/heads/aieh-probe-absent-00000000',
                                                          ':refs/heads/aieh-probe-absent-00000000',
                                                          ':refs/heads/feature/authz-protection-audit'])
        auditor_rows = [r for r in rows if r.get('role') == AUDITOR and 'if accepted' in r]
        self.assertEqual(len(auditor_rows), 29 + 4)
        self.assertTrue(all(r['if accepted'].startswith('made non-mutating') for r in auditor_rows))

    def test_the_other_roles_requests_are_those_of_7995a75(self):
        golden = json.loads(GOLDEN.read_text(encoding='utf-8'))
        self.assertEqual(golden['recorded_from'], '7995a75')
        current = authz_log()
        self.assertEqual(len(current), len(golden['authorization']))
        for n, (now, then) in enumerate(zip(current, golden['authorization'])):
            self.assertEqual(now, then, f'request {n}')
        self.assertTrue([e for e in current if e[0] == 'http'] and [e for e in current if e[0] == 'git'])

    def test_past_a_broken_scope_each_auditor_write_is_rejected_and_nothing_is_created(self):
        log = []
        fake = MatrixGitea(broken={AUDITOR}, mode='validate', log=log)
        before = fake.state()
        result, rows, breaker = authz_run(fake, FakeGit(log))
        self.assertIsNone(breaker.tripped_by)
        self.assertEqual(fake.state(), before)
        audited = fake.writes(AUDITOR)
        self.assertEqual(len(audited), 29)
        self.assertLessEqual({w['status'] for w in audited}, {400, 404, 422})
        for test, text in failures_of(result):
            self.assertIn("role='protection-audit'", test)
            self.assertNotIn('SECURITY FAILURE', text)
            self.assertTrue('not by the scope' in text or 'not exercised' in text, text)

    def test_the_bodies_and_targets_used_before_would_have_created_or_changed_something(self):
        """A control on the modelled validation: the auditor's requests before this correction (the other roles'
        bodies, its own login, the fixture)."""
        user = R.ROLES[AUDITOR]['user']
        former = [('POST', '/admin/actions/runners/registration-token', None),
                  ('POST', '/admin/users', {'username': 'aieh-probe-user', 'password': 'Probe-only-0123456789',
                                            'email': f'aieh-probe-user@{G.EMAIL_DOMAIN}'}),
                  ('PATCH', f'/admin/users/{user}', {'login_name': user, 'source_id': 0, 'admin': True}),
                  ('POST', f'/admin/users/{user}/orgs', {'username': 'aieh-probe-org'}),
                  *[('POST', f'/users/{u}/tokens', {'name': 'aieh-probe', 'scopes': ['all']})
                    for u in (user, G.OWNER, G.SITE_ADMIN)],
                  ('DELETE', f'/users/{G.OWNER}/tokens/1', None),
                  ('POST', '/user/repos', {'name': f'aieh-probe-{AUDITOR}', 'private': True}),
                  ('POST', '/orgs', {'username': f'aieh-probe-{AUDITOR}'}),
                  ('POST', f'/orgs/{R.FIXTURE_ORG}/repos', {'name': f'aieh-probe-{AUDITOR}'}),
                  ('PUT', '/user/actions/secrets/AIEH_PROBE', {'data': 'probe'}),
                  *[('POST', f'{FIXTURE}/pulls/1/merge', body) for body in A.merge_bodies()],
                  ('DELETE', f'{FIXTURE}/branches/main', None),
                  *A.settings_probes(user),
                  ('PUT', f'{FIXTURE}/actions/secrets/AIEH_PROBE', {'data': 'probe'})]
        for method, path, body in former:
            with self.subTest(method=method, path=path):
                fake = MatrixGitea(broken={AUDITOR}, mode='validate')
                before = fake.state()
                status = R.Api(3000, TOKENS[AUDITOR], fake).call(method, path, body)[0]
                self.assertIn(status, (200, 201, 204))
                self.assertNotEqual(fake.state(), before)

    def test_a_first_auditor_write_accepted_trips_the_breaker_and_no_later_write_is_sent(self):
        log = []
        fake, git = MatrixGitea(broken={AUDITOR}, mode='accept', log=log), FakeGit(log)
        result, rows, breaker = authz_run(fake, git)
        self.assertEqual(breaker.tripped_by, "protection-audit: POST /admin/users (invalid body) (POST /admin/users) "
                                             'answered 201')
        tripped = next(n for n, e in enumerate(log) if e.get('status') == 201 and e['role'] == AUDITOR)
        later = [e for e in log[tripped + 1:] if e['kind'] == 'git' and e['args'][0] == 'push'
                 or e['kind'] == 'http' and e['method'] not in READS]
        self.assertEqual(later, [])
        self.assertEqual(len(fake.writes(AUDITOR)), 1)
        self.assertTrue(breaker.withheld)
        self.assertIn('protection-audit: PATCH /admin/users/<absent> (make an absent user admin)', breaker.withheld)
        teardown = [text for test, text in result.errors if 'tearDownModule' in str(test)]
        self.assertEqual(len(teardown), 1)
        self.assertIn('SECURITY FAILURE in this run: the circuit breaker tripped at protection-audit: POST '
                      '/admin/users', teardown[0])
        self.assertEqual(rows[-1]['action'], 'circuit breaker')

    def test_any_role_accepted_trips_the_breaker_and_no_role_writes_after(self):
        log = []
        fake, git = MatrixGitea(broken={'planner'}, mode='accept', log=log), FakeGit(log)
        result, _rows, breaker = authz_run(fake, git)
        self.assertEqual(breaker.tripped_by, 'planner: the web sign-in form with a random password answered 303, '
                                             'not refused')
        self.assertEqual([e['path'] for e in log if e['kind'] == 'http' and e['method'] not in READS],
                         ['/user/login'])
        self.assertEqual(git.pushes(), [])
        self.assertTrue(any('tearDownModule' in str(test) for test, _t in result.errors))

    def test_a_push_that_must_be_denied_succeeding_trips_the_breaker(self):
        log = []
        fake, git = MatrixGitea(log=log), FakeGit(log, accept={'reviewer'})
        _result, _rows, breaker = authz_run(fake, git, classes=('TestFixtureDenied',))
        self.assertEqual(breaker.tripped_by, 'reviewer: a push to the protected main succeeded')
        tripped = max(n for n, e in enumerate(log) if e['kind'] == 'git' and e['role'] == 'reviewer'
                      and e['args'][0] == 'push')
        after = [e for e in log[tripped + 1:] if e['kind'] == 'git' and e['args'][0] == 'push'
                 or e['kind'] == 'http' and e['method'] not in READS]
        self.assertEqual([(e['method'], e['role']) for e in after], [('PATCH', 'builder'), ('PATCH', 'planner')])
        self.assertTrue(all(re.fullmatch(r'/api/v1/repos/[^/]+/[^/]+/pulls/\d+', e['path']) for e in after))

    def test_a_denied_write_answered_2xx_trips_the_breaker(self):
        log = []
        fake = MatrixGitea(broken={'verifier'}, mode='accept', log=log)
        result, _rows, breaker = authz_run(fake, FakeGit(log), classes=('TestInstanceWideDenials',))
        self.assertEqual(breaker.tripped_by, 'verifier: POST /admin/actions/runners/registration-token (POST '
                                             '/admin/actions/runners/registration-token) answered 201')
        tripped = next(n for n, e in enumerate(log) if e.get('status') == 201)
        self.assertEqual([e for e in log[tripped + 1:] if e['method'] not in READS], [])
        self.assertIn(f'{AUDITOR}: the remaining probes of test_admin_endpoints', breaker.withheld)
        self.assertTrue(any('tearDownModule' in str(test) for test, _t in result.errors))

    def test_main_moving_trips_the_breaker(self):
        log = []
        fake = MatrixGitea(log=log)

        def move(role, args):
            if role == 'reviewer' and args[-1] == 'HEAD:refs/heads/main':
                fake.branches['main'] = 'd' * 40
        _result, _rows, breaker = authz_run(fake, FakeGit(log, on_push=move), classes=('TestFixtureDenied',))
        self.assertEqual(breaker.tripped_by,
                         f'main moved during the push probes of reviewer ({"c" * 40} -> {"d" * 40})')
        reviewer_last = max(n for n, e in enumerate(log) if e['role'] == 'reviewer' and e['kind'] == 'git')
        self.assertFalse([e for e in log[reviewer_last + 1:] if e['kind'] == 'git'
                          and e['role'] in ('verifier', AUDITOR)])


class AuditorGitPushes(unittest.TestCase):
    """The auditor's pushes of the git suite with real git (--dry-run) against GiteaGit."""
    category = 'contract'

    @classmethod
    def setUpClass(cls):
        cls.server = GiteaGit()
        cls.addClassCleanup(cls.server.close)
        cls.tmp = Path(tempfile.mkdtemp(prefix='aieh-authz-git-'))
        cls.addClassCleanup(shutil.rmtree, cls.tmp, onexc=lambda f, p, e: (os.chmod(p, 0o700), f(p)))
        cls.ctx = SimpleNamespace(port=cls.server.port, tokens=dict(TOKENS))
        cls.clone = cls.tmp / 'clone'
        done = A.git(cls.ctx, AUDITOR, 'clone', '--quiet', cls.server.url, str(cls.clone), cwd=cls.tmp)
        assert done.returncode == 0, done.stderr

    def setUp(self):
        self.server.reset()
        self.before = self.server.refs()
        self.rows = []
        self.breaker = LB.Breaker(self.rows.append)
        for patch in (mock.patch.object(A, 'BREAKER', self.breaker), mock.patch.object(A, 'RESULTS', self.rows),
                      mock.patch.object(A, 'secrets', Deterministic),
                      mock.patch.object(G, 'http_get', GitApi(self.server))):
            patch.start()
            self.addCleanup(patch.stop)
        self.case = A.TestFixtureDenied('test_no_push_force_push_or_deletion_of_protected_refs')
        self.case.ctx = self.ctx

    def probes(self):
        orphan = A.git(self.ctx, AUDITOR, 'commit-tree', A.EMPTY_TREE, '-m', 'orphan', cwd=self.clone)
        return A.auditor_push_probes(orphan.stdout.decode().strip(), A.absent_name())

    def test_refused_at_the_advertisement_and_the_test_passes(self):
        self.case.auditor_pushes(self.clone)
        self.assertEqual([(r['method'], r['query']) for r in self.server.receive_pack()],
                         [('GET', 'service=git-receive-pack')] * 4)
        self.assertEqual(self.server.refs(), self.before)
        pushed = [r for r in self.rows if r['action'].startswith('git ')]
        self.assertEqual([r['status'] for r in pushed], [128] * 4)
        self.assertTrue(all(A.GIT_403 in r['message'] for r in pushed))
        self.assertIsNone(self.breaker.tripped_by)

    def test_served_each_push_sends_no_update_and_trips_the_breaker(self):
        self.server.serve, self.server.accept = {AUDITOR}, {AUDITOR}   # a Gitea that would apply anything
        for probe in self.probes():
            with self.subTest(probe=probe.action):
                self.server.requests.clear()
                breaker = LB.Breaker(self.rows.append)
                with mock.patch.object(A, 'BREAKER', breaker), self.assertRaises(LB.SecurityFailure) as caught:
                    self.case.auditor_push(self.clone, probe)
                self.assertNotIsInstance(caught.exception, LB.BreakerOpen)
                self.assertIn('served the receive-pack advertisement', breaker.tripped_by)
                self.assertEqual([(r['method'], r['query']) for r in self.server.receive_pack()],
                                 [('GET', 'service=git-receive-pack')])   # the advertisement, and no update
                self.assertEqual(self.server.refs(), self.before)

    def test_served_the_first_push_stops_the_rest(self):
        self.server.serve, self.server.accept = {AUDITOR}, {AUDITOR}
        with self.assertRaises(LB.SecurityFailure):
            self.case.auditor_pushes(self.clone)
        self.assertEqual(len(self.server.receive_pack()), 1)
        self.assertEqual(self.server.refs(), self.before)
        probes = self.probes()
        self.assertEqual(self.breaker.withheld, [f'{AUDITOR}: {p.action}' for p in probes[1:]]
                         + [f'{AUDITOR}: delete the default branch (API) (an absent repository)'])


class TransportRuns(unittest.TestCase):
    """The transport suite's matrix run whole through the repository module against GiteaGit."""
    category = 'contract'

    @classmethod
    def setUpClass(cls):
        cls.server = GiteaGit()
        cls.addClassCleanup(cls.server.close)
        cls.result, cls.rows, cls.breaker = transport_run(cls.server)
        cls.requests, cls.refs = list(cls.server.requests), cls.server.refs()

    def test_the_matrix_passes_and_leaves_only_the_proposal_commits(self):
        self.assertEqual(failures_of(self.result), [])
        self.assertIsNone(self.breaker.tripped_by)
        self.assertEqual(self.refs['refs/heads/main'], self.server.main.decode())
        self.assertEqual(sorted(self.refs), ['refs/heads/main', 'refs/heads/work/authz-builder',
                                             'refs/heads/work/authz-planner'])

    def test_each_auditor_push_is_refused_at_the_advertisement_and_sends_no_update(self):
        mine = [r for r in self.requests if r['role'] == AUDITOR and 'git-receive-pack' in r['path'] + r['query']]
        self.assertEqual([(r['method'], r['query']) for r in mine], [('GET', 'service=git-receive-pack')] * 5)
        rows = [r for r in self.rows if r.get('role') == AUDITOR and 'if accepted' in r]
        self.assertEqual([(r['outcome'], r['status']) for r in rows], [('PUSH_REFUSED', 403)] * 5)
        self.assertEqual([r['if accepted'] for r in rows],
                         [T.ABSENT_DELETE, T.NOT_FAST_FORWARD] + [T.ABSENT_DELETE] * 3)

    def test_the_other_roles_requests_are_those_of_7995a75(self):
        golden = json.loads(GOLDEN.read_text(encoding='utf-8'))['transport']
        current = transport_others(self.requests)
        self.assertEqual(len(current), len(golden))
        for n, (now, then) in enumerate(zip(current, golden)):
            self.assertEqual(now, then, f'request {n}')

    def test_the_auditor_served_trips_the_breaker_and_sends_no_update(self):
        self.server.reset()
        self.server.serve, self.server.accept = {AUDITOR}, {AUDITOR}
        try:
            result, _rows, breaker = transport_run(self.server)
            self.assertIn('protection-audit: push its proposal branch, standing in: delete the absent '
                          'work/authz-protection-audit (module): Gitea served the receive-pack advertisement',
                          breaker.tripped_by)
            self.assertIn('withheld the update (remote ref does not exist): no update was sent', breaker.tripped_by)
            mine = self.server.receive_pack(AUDITOR)
            self.assertEqual([(r['method'], r['query']) for r in mine], [('GET', 'service=git-receive-pack')])
            self.assertEqual(len(breaker.withheld), 4)
            self.assertEqual(sorted(self.server.refs()), ['refs/heads/main', 'refs/heads/work/authz-builder',
                                                          'refs/heads/work/authz-planner'])
            self.assertEqual(self.server.refs()['refs/heads/main'], self.server.main.decode())
            self.assertTrue(any('tearDownModule' in str(test) for test, _t in result.errors))
        finally:
            self.server.reset()

    def test_once_tripped_a_module_push_is_not_sent(self):
        breaker, call = LB.Breaker([].append), mock.Mock()
        breaker.fail('an earlier probe')
        case = T.TestMatrix('test_each_bot_through_the_module')
        with mock.patch.object(T, 'BREAKER', breaker), mock.patch.object(T, 'RESULTS', []):
            with self.assertRaises(LB.BreakerOpen):
                case.module('builder', 'push work/authz-builder (module)', 'allowed', call, write=True)
            with self.assertRaises(LB.BreakerOpen):
                case.denied_push('reviewer', 'force-push (module)', call)
        call.assert_not_called()
        self.assertEqual(breaker.withheld, ['builder: push work/authz-builder (module)',
                                            'reviewer: force-push (module)'])

    def test_main_moving_trips_the_breaker(self):
        self.server.reset()
        self.server.move_main = 'reviewer'
        try:
            _result, _rows, breaker = transport_run(self.server)
            self.assertTrue(breaker.tripped_by.startswith('main moved during the pushes of reviewer'),
                            breaker.tripped_by)
            self.assertEqual(self.server.receive_pack('verifier') + self.server.receive_pack(AUDITOR), [])
        finally:
            self.server.reset()

    def test_served_each_auditor_push_sends_no_update(self):
        self.server.reset()
        self.server.serve, self.server.accept = {AUDITOR}, {AUDITOR}   # a Gitea that would apply anything
        tmp = Path(tempfile.mkdtemp(prefix='aieh-transport-safety-'))
        self.addCleanup(shutil.rmtree, tmp, onexc=lambda f, p, e: (os.chmod(p, 0o700), f(p)))
        credential = RA.Credential(R.ROLES[AUDITOR]['user'], TOKENS[AUDITOR])
        RA.clone(self.server.url, tmp / 'clone.git', credential)
        before = self.server.refs()
        case = T.TestMatrix('test_each_bot_through_the_module')
        case.url = self.server.url
        try:
            with (mock.patch.object(T, 'RESULTS', []), mock.patch.object(T.TestMatrix, 'launched', 0, create=True),
                  RA.open_repository(tmp / 'clone.git', config='repository', work_tree=False, ceilings=[tmp]) as repo):
                orphan = case.new_commit(repo, AUDITOR, None, 'orphan')
                for probe in T.auditor_push_probes(orphan, 'aieh-probe-absent-00000000'):
                    with self.subTest(probe=probe.action):
                        self.server.requests.clear()
                        breaker = LB.Breaker([].append)
                        with mock.patch.object(T, 'BREAKER', breaker), self.assertRaises(LB.SecurityFailure):
                            case.auditor_push(repo, probe, credential)
                        self.assertIn('withheld the update', breaker.tripped_by)
                        self.assertEqual([(r['method'], r['query']) for r in self.server.receive_pack()],
                                         [('GET', 'service=git-receive-pack')])
                        self.assertEqual(self.server.refs(), before)
        finally:
            self.server.reset()

    def test_another_role_accepted_trips_the_breaker_and_no_later_push_is_sent(self):
        self.server.reset()
        self.server.accept = {'planner'}   # the protected branch takes planner's push
        try:
            _result, _rows, breaker = transport_run(self.server)
            self.assertTrue(breaker.tripped_by.startswith('planner: push to the protected branch (module) succeeded'),
                            breaker.tripped_by)
            posts = [n for n, r in enumerate(self.server.requests) if r['method'] == 'POST'
                     and 'git-receive-pack' in r['path']]
            tripped = posts[1]   # planner's proposal push, then the protected one
            self.assertEqual([r for r in self.server.requests[tripped + 1:] if 'git-receive-pack' in r['path']
                              + r['query']], [])
            self.assertEqual({r['role'] for r in self.server.requests}, {'planner'})
            self.assertTrue(any(w.startswith('builder: the remaining pushes') for w in breaker.withheld))
        finally:
            self.server.reset()


if __name__ == '__main__':
    unittest.main()
