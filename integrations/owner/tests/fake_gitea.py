"""A fake Gitea 28.3.0 for the Owner authorization recorder's tests (plan leaf P-04.2).

``FakeGitea`` models the slice of Gitea's API the recorder uses, with the behaviour read in the pinned
source (gitea-src-28.3.0, see evidence/P-04.2-authorization-recorder.md): HTTP basic authentication and
token authentication; ``GET /user``; ``GET /users/{user}/tokens`` (basic authentication, the account
itself); the repository with the caller's permissions and merge settings; a branch with the protection
fields a non-administrator sees (protected, required approvals, status checks, user_can_push,
user_can_merge); a pull request, its files, raw files at a commit and a commit with its parents and
message; and ``POST /pulls/{index}/merge`` (``Do``, ``merge_title_field``, ``merge_message_field``,
``head_commit_id``): 405 for a caller outside the merge allowlist or a merge style the repository does not
allow, 409 "head out of date" when ``head_commit_id`` is not the head, otherwise a merge commit with the
base and the head as parents and the message title, a blank line, then the message.

It is callable in memory (``fake(port, path, method=..., body=..., headers=..., timeout=...)``, the
signature of gitea_host.http_get) and served over host loopback by ``Server`` (one in-process
ThreadingHTTPServer), which can drop a connection without an answer: a lost answer. Every value here is
synthetic: no real credential, token or Gitea is involved.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import http.server
import json
import threading
import urllib.parse

REPOSITORY = 'aieh-authz-fixture/authz'
OWNER = 'aieh-owner'
BOTS = ('aieh-bot-planner', 'aieh-bot-builder', 'aieh-bot-reviewer', 'aieh-bot-verifier')
# Synthetic secrets: the password of the fake aieh-owner and one token per fake bot (40 hex digits).
PASSWORD = 'synthetic-owner-password-not-a-real-credential'
BOT_TOKENS = {bot: hashlib.sha1(f'synthetic token {bot}'.encode()).hexdigest() for bot in BOTS}
DROP = object()  # the server closes the connection without an answer


def sha(*parts) -> str:
    return hashlib.sha1('\x00'.join(str(p) for p in parts).encode('utf-8')).hexdigest()


class FakeGitea:
    def __init__(self):
        self.users = {OWNER: {'password': PASSWORD, 'is_admin': False, 'tokens': []}}
        for bot in BOTS:
            self.users[bot] = {'password': None, 'is_admin': False, 'tokens': []}
        self.basic_as = {}            # {(user, password): login}: a credential that signs in as someone else
        self.repo = {'full_name': REPOSITORY, 'private': True, 'archived': False, 'default_branch': 'main',
                     'allow_merge_commits': True, 'allow_rebase': True, 'allow_squash_merge': True}
        self.permissions = {OWNER: {'admin': False, 'push': True, 'pull': True}}
        self.protection = {'main': {'required_approvals': 1, 'enable_status_check': False,
                                    'status_check_contexts': [], 'merge_whitelist': [OWNER], 'push_whitelist': []}}
        self.commits, self.branches, self.pulls = {}, {}, {}
        root = self.commit([], {'README.md': b'Authorization fixture\n'}, 'Initial commit')
        self.branches['main'] = root
        self.requests, self.merge_bodies, self.merges = [], [], 0
        self.on_merge = None          # 'drop', 'drop-before', 'error-after' or 'move-head'
        self.lock = threading.Lock()

    # ------------------------------------------------------------------ the repository's history

    def commit(self, parents, tree, message) -> str:
        commit_id = sha('commit', len(self.commits), *parents, message)
        self.commits[commit_id] = {'parents': list(parents), 'tree': dict(tree), 'message': message}
        return commit_id

    def propose(self, files, *, author='aieh-bot-builder', branch='work/op', title='Operation proposal',
                state='open', mergeable=True, base=None) -> int:
        """A pull request from BRANCH (a new commit adding FILES on BASE, by default the protected branch's
        head) into main."""
        base = base or self.branches['main']
        tree = {**self.commits[base]['tree'], **files}
        head = self.commit([base], tree, f'Propose {", ".join(files)}')
        self.branches[branch] = head
        number = len(self.pulls) + 1
        self.pulls[number] = {'state': state, 'title': title, 'user': author, 'base': 'main', 'head_ref': branch,
                              'base_at_open': base, 'merged': False, 'merged_by': None, 'merge_commit_sha': None,
                              'mergeable': mergeable, 'head_repo': REPOSITORY}
        return number

    def head(self, number) -> str:
        return self.branches[self.pulls[number]['head_ref']]

    def push_to_head(self, number, files, message='Change the proposal'):
        """A new commit on the pull request's branch (the head moves)."""
        head = self.head(number)
        self.branches[self.pulls[number]['head_ref']] = self.commit([head], {**self.commits[head]['tree'], **files},
                                                                    message)

    def advance_main(self, files, message='Another change on main'):
        base = self.branches['main']
        self.branches['main'] = self.commit([base], {**self.commits[base]['tree'], **files}, message)

    # ------------------------------------------------------------------ HTTP

    def __call__(self, port, path, *, method='GET', body=None, headers=None, timeout=5.0):
        answer = self.handle(method, path, headers or {}, body)
        if answer is DROP:
            raise ConnectionResetError('the fake Gitea dropped the connection without an answer')
        return answer

    def handle(self, method, path, headers, body):
        with self.lock:
            return self._handle(method, path, headers, body)

    @staticmethod
    def reply(status, payload):
        data = b'' if payload is None else (payload if isinstance(payload, bytes) else json.dumps(payload).encode())
        return status, {'content-type': 'application/json'}, data

    def doer(self, headers):
        auth = {k.lower(): v for k, v in headers.items()}.get('authorization', '')
        if auth.startswith('Basic '):
            user, _, password = base64.b64decode(auth[6:]).decode('utf-8').partition(':')
            if (user, password) in self.basic_as:
                return self.basic_as[(user, password)], 'basic'
            entry = self.users.get(user)
            if entry is not None and entry['password'] is not None and entry['password'] == password:
                return user, 'basic'
            return None, 'basic'
        if auth.startswith('token '):
            for bot, token in BOT_TOKENS.items():
                if auth[6:] == token:
                    return bot, 'token'
            return None, 'token'
        return None, None

    def _handle(self, method, path, headers, body):
        doer, kind = self.doer(headers)
        lowered = {k.lower(): v for k, v in headers.items()}
        self.requests.append({'method': method, 'path': path, 'auth': kind, 'doer': doer,
                              'sudo': 'sudo' in lowered or 'sudo=' in path})
        if doer is None:
            return self.reply(401, {'message': 'unauthorized'})
        parsed = urllib.parse.urlsplit(path)
        query = dict(urllib.parse.parse_qsl(parsed.query))
        route = parsed.path.removeprefix('/api/v1')
        repo = f'/repos/{REPOSITORY}'
        if method == 'GET' and route == '/user':
            return self.reply(200, {'login': doer, 'is_admin': self.users[doer]['is_admin']})
        if method == 'GET' and route.startswith('/users/') and route.endswith('/tokens'):
            user = route[len('/users/'):-len('/tokens')]
            if kind != 'basic':
                return self.reply(401, {'message': 'auth required'})
            if user != doer:
                return self.reply(403, {'message': 'doer should be the site admin or be same as the contextUser'})
            return self.reply(200, [{'id': n + 1, 'name': name} for n, name in enumerate(self.users[user]['tokens'])])
        if method == 'GET' and route == repo:
            return self.reply(200, {**self.repo, 'permissions': self.permissions.get(doer, {'admin': False,
                                                                                         'push': False,
                                                                                         'pull': True})})
        if method == 'GET' and route.startswith(f'{repo}/branches/'):
            name = urllib.parse.unquote(route[len(f'{repo}/branches/'):])
            if name not in self.branches:
                return self.reply(404, {'message': 'branch not found'})
            rule = self.protection.get(name)
            view = {'name': name, 'commit': {'id': self.branches[name]}, 'protected': rule is not None,
                    'required_approvals': rule['required_approvals'] if rule else 0,
                    'enable_status_check': rule['enable_status_check'] if rule else False,
                    'status_check_contexts': list(rule['status_check_contexts']) if rule else [],
                    'user_can_push': doer in rule['push_whitelist'] if rule else True,
                    'user_can_merge': doer in rule['merge_whitelist'] if rule else True}
            return self.reply(200, view)
        if route.startswith(f'{repo}/pulls/'):
            rest = route[len(f'{repo}/pulls/'):].split('/')
            number = int(rest[0]) if rest[0].isdigit() else None
            if number not in self.pulls:
                return self.reply(404, {'message': 'pull request not found'})
            if method == 'GET' and len(rest) == 1:
                return self.reply(200, self.pull_view(number))
            if method == 'GET' and rest[1:] == ['files']:
                return self.reply(200, self.files(number))
            if method == 'POST' and rest[1:] == ['merge']:
                return self.merge(number, doer, json.loads(body) if body else {})
        if method == 'GET' and route.startswith(f'{repo}/raw/'):
            file_path = urllib.parse.unquote(route[len(f'{repo}/raw/'):])
            commit = self.commits.get(query.get('ref', ''))
            if commit is None or file_path not in commit['tree']:
                return self.reply(404, {'message': 'not found'})
            return 200, {'content-type': 'application/octet-stream'}, commit['tree'][file_path]
        if method == 'GET' and route.startswith(f'{repo}/git/commits/'):
            commit_id = route[len(f'{repo}/git/commits/'):]
            commit = self.commits.get(commit_id)
            if commit is None:
                return self.reply(404, {'message': 'commit not found'})
            return self.reply(200, {'sha': commit_id, 'commit': {'message': commit['message']},
                                    'parents': [{'sha': p} for p in commit['parents']]})
        return self.reply(404, {'message': f'no route {method} {route}'})

    def pull_view(self, number):
        pr = self.pulls[number]
        return {'number': number, 'state': pr['state'], 'title': pr['title'], 'user': {'login': pr['user']},
                'merged': pr['merged'], 'mergeable': pr['mergeable'],
                'merged_by': {'login': pr['merged_by']} if pr['merged_by'] else None,
                'merge_commit_sha': pr['merge_commit_sha'],
                'base': {'ref': pr['base'], 'sha': self.branches[pr['base']], 'repo': {'full_name': REPOSITORY}},
                'head': {'ref': pr['head_ref'], 'sha': self.head(number), 'repo': {'full_name': pr['head_repo']}}}

    def files(self, number):
        pr = self.pulls[number]
        before, after = self.commits[pr['base_at_open']]['tree'], self.commits[self.head(number)]['tree']
        out = []
        for name in sorted(set(before) | set(after)):
            if name not in before:
                out.append({'filename': name, 'status': 'added'})
            elif name not in after:
                out.append({'filename': name, 'status': 'removed'})
            elif before[name] != after[name]:
                out.append({'filename': name, 'status': 'modified'})
        return out

    def merge(self, number, doer, form):
        self.merge_bodies.append(copy.deepcopy(form))
        pr = self.pulls[number]
        if self.on_merge == 'drop-before':
            return DROP
        if self.on_merge == 'move-head':
            self.push_to_head(number, {'operations/late.txt': b'moved after the challenge\n'})
        if pr['state'] != 'open':
            return self.reply(404, {'message': 'not found'})
        if pr['merged']:
            return self.reply(405, {'message': 'The PR is already merged'})
        rule = self.protection.get(pr['base'])
        if form.get('force_merge') or form.get('merge_when_checks_succeed'):
            return self.reply(405, {'message': 'the fake refuses force and scheduled merges'})
        if rule is not None and doer not in rule['merge_whitelist']:
            return self.reply(405, {'message': 'User not allowed to merge PR'})
        if form.get('Do') != 'merge' or not self.repo['allow_merge_commits']:
            return self.reply(405, {'message': f'{form.get("Do")} is not allowed an allowed merge style for this '
                                               'repository'})
        head = self.head(number)
        if form.get('head_commit_id') and form['head_commit_id'] != head:
            return self.reply(409, {'message': 'head out of date'})
        message = form.get('merge_title_field', '').strip()
        if form.get('merge_message_field', '').strip():
            message += '\n\n' + form['merge_message_field'].strip()
        base = self.branches[pr['base']]
        tree = {**self.commits[base]['tree'], **self.commits[head]['tree']}
        merged = self.commit([base, head], tree, message + '\n')
        self.branches[pr['base']] = merged
        pr.update(state='closed', merged=True, merged_by=doer, merge_commit_sha=merged)
        self.merges += 1
        if self.on_merge == 'drop':
            return DROP
        if self.on_merge == 'error-after':
            return self.reply(500, {'message': 'internal error after the push'})
        return self.reply(200, None)

    def merge_count(self):
        return self.merges

    def requests_by(self, method):
        return [r for r in self.requests if r['method'] == method]


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def _serve(self):
        length = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(length) if length else None
        answer = self.server.gitea.handle(self.command, self.path, dict(self.headers.items()), body)
        if answer is DROP:
            self.close_connection = True
            return
        status, headers, data = answer
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = do_DELETE = do_PATCH = _serve

    def log_message(self, *args):  # quiet
        pass


class Server:
    """One in-process HTTP server on 127.0.0.1 serving the current FakeGitea (``server.gitea``)."""

    def __init__(self):
        self.httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
        self.httpd.daemon_threads = True
        self.httpd.gitea = FakeGitea()
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
        self.thread.start()

    @property
    def gitea(self):
        return self.httpd.gitea

    def reset(self) -> FakeGitea:
        self.httpd.gitea = FakeGitea()
        return self.httpd.gitea

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()


class FixtureProvider:
    """A fixture credential provider (the lifecycle contract's get, set, delete): entries in memory only,
    never the platform's store. ``reads`` lists the entry names read."""

    def __init__(self, entries=None):
        self.entries = dict(entries or {})
        self.reads = []

    def get(self, name):
        self.reads.append(name)
        return self.entries.get(name)

    def set(self, name, user, secret, comment=''):
        self.entries[name] = (user, secret)

    def delete(self, name):
        return self.entries.pop(name, None) is not None
