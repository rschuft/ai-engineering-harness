"""The repository module's smart-HTTP transports against a local server (plan leaf F-10.6).

Run from the repository root, under the tools interpreter (Dulwich is required):

    <tools python> -I -B -m unittest discover -s integrations/repository/tests -v

The server is Dulwich's own smart-HTTP application (``dulwich.web``) under the standard
library's ``wsgiref``, on 127.0.0.1 in a thread of this process, behind a small authorization
layer that answers 401 and 403 as Gitea does and records every request's ``Authorization``
header. Every repository is built here with Dulwich's object API: no git, no process. The live
qualification against the host Gitea is ``integrations/gitea/tests/test_transport_live.py``
(opt-in, ``gitea:transport``).
"""
import base64
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer

CATEGORY = 'contract'

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import repository_corpus  # noqa: E402,F401  (puts integrations/repository on sys.path)
import repository_access as ra  # noqa: E402

BASIC = ra.Credential('writer-bot', 'basic-secret-0123456789abcdef')
TOKEN = ra.Credential('token-bot', 'token-secret-fedcba9876543210', scheme='token')
READER = ra.Credential('reader-bot', 'reader-secret-0011223344556677', scheme='token')
WRONG = ra.Credential('writer-bot', 'not-the-secret', scheme='token')
SECRETS = [c.secret for c in (BASIC, TOKEN, READER, WRONG)]
PROTECTED = b'refs/heads/protected'
WHEN = 1762992000  # 2025-11-13T00:00:00Z, fixed so object ids are stable


def rmtree(path):
    def retry(func, target, _exc):
        os.chmod(target, stat.S_IWRITE)
        func(target)
    shutil.rmtree(path, onexc=retry)


def dulwich():
    d = ra.dulwich_modules()
    from dulwich import errors, objects, repo, server, web
    return d, errors, objects, repo, server, web


def commit(repository, parents, files, message):
    """A commit of the flat FILES ({name: bytes}) on PARENTS, written with Dulwich's object API."""
    _d, _e, objects, _r, _s, _w = dulwich()
    tree = objects.Tree()
    added = []
    for name, data in sorted(files.items()):
        blob = objects.Blob.from_string(data)
        added.append(blob)
        tree.add(name.encode(), 0o100644, blob.id)
    made = objects.Commit()
    made.tree, made.parents = tree.id, list(parents)
    made.author = made.committer = b'Transport Test <transport@example.invalid>'
    made.author_time = made.commit_time = WHEN + len(added) + len(parents)
    made.author_timezone = made.commit_timezone = 0
    made.message = message.encode() + b'\n'
    for obj in (*added, tree, made):
        repository.object_store.add_object(obj)
    return made.id


def annotated_tag(repository, name, target):
    _d, _e, objects, _r, _s, _w = dulwich()
    tag = objects.Tag()
    tag.name, tag.object = name, (objects.Commit, target)
    tag.tagger = b'Transport Test <transport@example.invalid>'
    tag.tag_time, tag.tag_timezone, tag.message = WHEN, 0, b'a tag\n'
    repository.object_store.add_object(tag)
    return tag.id


class Quiet(WSGIRequestHandler):
    def log_message(self, *_args):
        pass


class Server:
    """One smart-HTTP server on 127.0.0.1 for the whole module (``server()``), serving the current
    ``Remote`` at /org/repo.git. Started on first use, stopped by ``stop_server()``."""

    def __init__(self):
        self.current = None
        self.httpd = WSGIServer(('127.0.0.1', 0), Quiet)
        self.httpd.set_app(self.app)
        self.base = f'http://127.0.0.1:{self.httpd.server_address[1]}'
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
        self.thread.start()

    def app(self, environ, start_response):
        remote = self.current
        if remote is None:
            start_response('404 Not Found', [('Content-Type', 'text/plain')])
            return [b'no remote\n']
        return remote.app(environ, start_response)

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()


_SERVER = []


def server():
    if not _SERVER:
        _SERVER.append(Server())
    return _SERVER[0]


def stop_server():
    while _SERVER:
        _SERVER.pop().close()


def tearDownModule():
    stop_server()
    stop_golden()


class Remote:
    """A bare repository served at <server>/org/repo.git: in memory, or at PATH on disk (for git's
    fsck). Credentials: BASIC and TOKEN may push; READER may only read (403 on receive-pack);
    anything else, or none, is 401. An ``update`` hook (in process) declines every update of
    refs/heads/protected, as a protected branch does. The served repository reads no user or
    system git configuration."""

    def __init__(self, path=None):
        _d, errors, _o, repo, dserver, web = dulwich()
        from dulwich.config import StackedConfig
        self.path = path
        if path is None:
            self.repo = repo.MemoryRepo()
        else:
            path.mkdir()
            self.repo = repo.Repo.init_bare(str(path), config=StackedConfig([]), default_branch=b'main')
        r = self.repo
        r.get_config_stack = lambda: StackedConfig([r.get_config()])
        self.requests = []

        class Protect:
            def execute(self, ref, old, new):
                if ref == PROTECTED:
                    raise errors.HookError('protected branch')
                return b'', b''

        r.hooks = {'update': Protect()}
        # make_wsgi_chain limits the request body to its Content-Length (wsgiref does not).
        app = web.make_wsgi_chain(dserver.DictBackend({'/org/repo.git': r}))
        allowed = {BASIC.authorization(): 'write', TOKEN.authorization(): 'write', READER.authorization(): 'read'}
        requests = self.requests

        def authorizing(environ, start_response):
            header = environ.get('HTTP_AUTHORIZATION')
            requests.append((environ['REQUEST_METHOD'], environ['PATH_INFO'], environ.get('QUERY_STRING', ''),
                             header))
            right = allowed.get(header)
            receive = 'git-receive-pack' in environ['PATH_INFO'] + environ.get('QUERY_STRING', '')
            if right is None:
                start_response('401 Unauthorized', [('WWW-Authenticate', 'Basic realm="test"'),
                                                    ('Content-Type', 'text/plain')])
                return [b'authentication required\n']
            if receive and right != 'write':
                start_response('403 Forbidden', [('Content-Type', 'text/plain')])
                return [b'read only\n']
            return app(environ, start_response)

        self.app = authorizing
        shared = server()
        shared.current = self
        self.url = f'{shared.base}/org/repo.git'

    def close(self):
        if _SERVER and _SERVER[0].current is self:
            _SERVER[0].current = None
        self.repo.close()

    def refs(self):
        return {k: v for k, v in self.repo.get_refs().items()}


def closure(store, oid):
    """The commit OID, its tree and the tree's blobs (flat trees only)."""
    made = store[oid]
    return [made, store[made.tree], *(store[sha] for _n, _m, sha in store[made.tree].iteritems())]


def history(repository):
    """main: two commits; protected; a lightweight and an annotated tag (the remote's)."""
    ids = {'c1': commit(repository, [], {'a.txt': b'one\n'}, 'first')}
    ids['c2'] = commit(repository, [ids['c1']], {'a.txt': b'two\n'}, 'second')
    ids['tag'] = annotated_tag(repository, b'v1', ids['c1'])
    return ids


_GOLDEN = []


def golden():
    """(directory, ids): the local bare repository, built once per process with Dulwich (its
    disk writes are synced, so each test copies it): the remote's history, one commit on top of
    main and an orphan."""
    if not _GOLDEN:
        _d, _e, _o, repo, _s, _w = dulwich()
        from dulwich.config import StackedConfig
        root = Path(tempfile.mkdtemp(prefix='aieh-transport-golden-'))
        path = root / 'local.git'
        path.mkdir()
        local = repo.Repo.init_bare(str(path), config=StackedConfig([]), default_branch=b'main')
        scratch = repo.MemoryRepo()
        ids = history(scratch)
        for oid in (ids['c1'], ids['c2']):
            for obj in closure(scratch.object_store, oid):
                local.object_store.add_object(obj)
        ids['c3'] = commit(local, [ids['c2']], {'a.txt': b'three\n'}, 'third')
        ids['orphan'] = commit(local, [], {'b.txt': b'orphan\n'}, 'orphan')
        local.refs[b'refs/heads/main'] = ids['c3']
        local.close()
        _GOLDEN.append((root, path, ids))
    return _GOLDEN[0]


def stop_golden():
    while _GOLDEN:
        rmtree(_GOLDEN.pop()[0])


def served(path=None):
    """The served remote (in memory, or a bare repository at PATH on disk) and the object ids of
    the remote and of the golden local repository."""
    remote = Remote(path)
    r = remote.repo
    ids = dict(golden()[2])
    assert history(r) == {k: ids[k] for k in ('c1', 'c2', 'tag')}
    r.refs[b'refs/heads/main'] = ids['c2']
    r.refs[PROTECTED] = ids['c2']
    r.refs[b'refs/tags/light'] = ids['c1']
    r.refs[b'refs/tags/v1'] = ids['tag']
    r.refs.set_symbolic_ref(b'HEAD', b'refs/heads/main')
    return remote, ids


def local_copy(destination):
    """A copy of the golden local repository at DESTINATION."""
    shutil.copytree(golden()[1], destination)
    return destination


class TransportCase(unittest.TestCase):
    """A fresh served remote per test; one copy of the golden local repository per class (a push
    writes nothing locally); process creation and Dulwich's user and system configuration
    patched to fail."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='aieh-transport-'))
        cls.addClassCleanup(rmtree, cls.tmp)
        cls.local = ra.open_repository(local_copy(cls.tmp / 'local.git'), config='repository', work_tree=False,
                                       ceilings=[cls.tmp])
        cls.addClassCleanup(cls.local.close)

    def setUp(self):
        self.remote, ids = served()
        self.addCleanup(self.remote.close)
        for name, oid in ids.items():
            setattr(self, name, oid)
        from dulwich.config import StackedConfig
        for patch in (mock.patch.object(subprocess, 'Popen', side_effect=AssertionError('a process was launched')),
                      mock.patch.object(StackedConfig, 'default_backends',
                                        side_effect=AssertionError('user or system git configuration read'))):
            patch.start()
            self.addCleanup(patch.stop)

    def expect(self, code, call, *args, **kwargs):
        with self.assertRaises(ra.RepositoryError) as caught:
            call(*args, **kwargs)
        self.assertEqual(caught.exception.code, code, caught.exception)
        self.assertNoSecret(str(caught.exception), repr(caught.exception.details))
        return caught.exception

    def assertNoSecret(self, *texts):
        for text in texts:
            for secret in SECRETS:
                self.assertNotIn(secret, text)

    def headers(self):
        return {header for *_rest, header in self.remote.requests}


class Credentials(unittest.TestCase):
    category = 'unit'

    def test_the_secret_is_never_shown(self):
        for credential in (BASIC, TOKEN):
            self.assertNotIn(credential.secret, repr(credential))
            self.assertNotIn(credential.secret, str(credential))
            self.assertNotIn(credential.secret, f'{credential}')
            self.assertIn('<hidden>', repr(credential))

    def test_the_header_values(self):
        self.assertEqual(BASIC.authorization(),
                         'Basic ' + base64.b64encode(b'writer-bot:basic-secret-0123456789abcdef').decode())
        self.assertEqual(TOKEN.authorization(), 'token token-secret-fedcba9876543210')

    def test_refused_credentials(self):
        for kwargs in ({'username': 'u', 'secret': 's', 'scheme': 'bearer'}, {'username': '', 'secret': 's'},
                       {'username': 'u', 'secret': ''}, {'username': 'a:b', 'secret': 's'},
                       {'username': 'u', 'secret': 's\r\nX-Injected: 1'}, {'username': 'u', 'secret': None}):
            with self.subTest(**{k: repr(v) for k, v in kwargs.items()}), self.assertRaises(ValueError):
                ra.Credential(**kwargs)

    def test_refused_urls_before_any_access(self):
        with mock.patch.object(ra, '_transport_modules', side_effect=AssertionError('accessed')):
            for url in ('ssh://git@example.invalid/org/repo.git', 'git@example.invalid:org/repo.git',
                        'file:///D:/work/repo', 'D:/work/repo', 'git://example.invalid/repo',
                        'https://user:pw@example.invalid/repo.git', 'https://tok@example.invalid/repo.git',
                        'https://example.invalid/repo.git?token=x', 'https://example.invalid/repo.git#x',
                        'https://example.invalid/re\npo.git', None):
                with self.subTest(url=url), self.assertRaises(ValueError):
                    ra.ls_remote(url)
            with self.assertRaises(ValueError):
                ra.ls_remote('https://example.invalid/repo.git', credential=('u', 'p'))
            for names in ('refs/heads/main', ['main'], ['refs/heads/a..b']):
                with self.subTest(names=names), self.assertRaises(ValueError):
                    ra.ls_remote('https://example.invalid/repo.git', names=names)


class LsRemote(TransportCase):
    def test_lists_as_git_ls_remote(self):
        refs = ra.ls_remote(self.remote.url, BASIC)
        self.assertEqual(refs, {'HEAD': self.c2.decode(), 'refs/heads/main': self.c2.decode(),
                                'refs/heads/protected': self.c2.decode(), 'refs/tags/light': self.c1.decode(),
                                'refs/tags/v1': self.tag.decode(), 'refs/tags/v1^{}': self.c1.decode()})

    def test_names_keep_only_those(self):
        self.assertEqual(ra.ls_remote(self.remote.url, TOKEN, names=['refs/tags/v1']),
                         {'refs/tags/v1': self.tag.decode(), 'refs/tags/v1^{}': self.c1.decode()})
        self.assertEqual(ra.ls_remote(self.remote.url, TOKEN, names=['refs/tags/light']),
                         {'refs/tags/light': self.c1.decode()})
        self.assertEqual(ra.ls_remote(self.remote.url, TOKEN, names=['refs/tags/v']), {})

    def test_each_scheme_sends_its_header_and_nothing_else(self):
        ra.ls_remote(self.remote.url, BASIC)
        self.assertEqual(self.headers(), {BASIC.authorization()})
        self.remote.requests.clear()
        ra.ls_remote(self.remote.url, TOKEN)
        self.assertEqual(self.headers(), {'token ' + TOKEN.secret})

    def test_refused_and_failed(self):
        error = self.expect('REMOTE_REFUSED', ra.ls_remote, self.remote.url)
        self.assertEqual(error.details['status'], 401)
        self.assertEqual(self.headers(), {None})
        self.expect('REMOTE_REFUSED', ra.ls_remote, self.remote.url, WRONG)
        self.expect('REMOTE_FAILED', ra.ls_remote, self.remote.url.replace('repo.git', 'none.git'), BASIC)
        closed = socket_closed()
        with closed as url:
            self.expect('REMOTE_FAILED', ra.ls_remote, url, BASIC)
        self.assertEqual(closed.accepted, 1)  # one attempt, as git makes: no retry


class socket_closed:
    """A loopback URL whose server accepts each connection and closes it without an answer (a
    port with no listener costs Windows about two seconds of retransmissions per connection)."""

    def __enter__(self):
        import socket
        self.server = socket.create_server(('127.0.0.1', 0))
        self.server.settimeout(10)
        self.accepted = 0

        def hang_up():
            while True:
                try:
                    connection, _ = self.server.accept()
                except OSError:
                    return
                self.accepted += 1
                connection.close()

        self.thread = threading.Thread(target=hang_up, daemon=True)
        self.thread.start()
        return f'http://127.0.0.1:{self.server.getsockname()[1]}/org/repo.git'

    def __exit__(self, *exc):
        self.server.close()
        self.thread.join()
        return False


class Push(TransportCase):
    def test_a_fast_forward_and_a_new_branch(self):
        update = self.local.push(self.remote.url, 'HEAD:refs/heads/main', BASIC)
        self.assertEqual(update, ra.RefUpdate('refs/heads/main', self.c2.decode(), self.c3.decode()))
        self.assertEqual(self.remote.refs()[b'refs/heads/main'], self.c3)
        update = self.local.push(self.remote.url, f'{self.c3.decode()[:12]}:refs/heads/work/x', TOKEN)
        self.assertEqual(update, ra.RefUpdate('refs/heads/work/x', None, self.c3.decode()))
        self.assertEqual(self.remote.refs()[b'refs/heads/work/x'], self.c3)
        self.assertEqual(self.headers(), {BASIC.authorization(), TOKEN.authorization()})

    def test_up_to_date_sends_nothing_and_succeeds(self):
        update = self.local.push(self.remote.url, f'{self.c2.decode()}:refs/heads/main', BASIC)
        self.assertEqual(update, ra.RefUpdate('refs/heads/main', self.c2.decode(), self.c2.decode()))
        self.assertEqual([m for m, *_ in self.remote.requests], ['GET'])

    def test_not_a_fast_forward_is_rejected_before_sending_unless_forced(self):
        before = self.remote.refs()
        error = self.expect('PUSH_REJECTED', self.local.push, self.remote.url,
                            f'{self.orphan.decode()}:refs/heads/main', BASIC)
        self.assertEqual(error.details['reason'], 'non-fast-forward')
        self.expect('PUSH_REJECTED', self.local.push, self.remote.url, f'{self.c1.decode()}:refs/heads/main', BASIC)
        self.assertEqual(self.remote.refs(), before)
        self.assertEqual([m for m, *_ in self.remote.requests], ['GET', 'GET'])  # nothing was sent
        update = self.local.push(self.remote.url, f'+{self.orphan.decode()}:refs/heads/main', BASIC)
        self.assertEqual(update.new, self.orphan.decode())
        self.assertEqual(self.remote.refs()[b'refs/heads/main'], self.orphan)

    def test_an_unknown_remote_tip_is_fetch_first(self):
        r = self.remote.repo
        elsewhere = commit(r, [self.c2], {'a.txt': b'elsewhere\n'}, 'elsewhere')
        r.refs[b'refs/heads/main'] = elsewhere
        error = self.expect('PUSH_REJECTED', self.local.push, self.remote.url, 'HEAD:refs/heads/main', BASIC)
        self.assertEqual(error.details['reason'], 'fetch first')
        self.local.push(self.remote.url, '+HEAD:refs/heads/main', BASIC)
        self.assertEqual(self.remote.refs()[b'refs/heads/main'], self.c3)

    def test_an_existing_tag_is_not_replaced_unless_forced(self):
        error = self.expect('PUSH_REJECTED', self.local.push, self.remote.url, 'HEAD:refs/tags/light', BASIC)
        self.assertEqual(error.details['reason'], 'already exists')
        self.local.push(self.remote.url, '+HEAD:refs/tags/light', BASIC)
        self.assertEqual(self.remote.refs()[b'refs/tags/light'], self.c3)

    def test_delete(self):
        self.local.push(self.remote.url, f'{self.c2.decode()}:refs/heads/gone', BASIC)
        update = self.local.push(self.remote.url, ':refs/heads/gone', BASIC)
        self.assertEqual(update, ra.RefUpdate('refs/heads/gone', self.c2.decode(), None))
        self.assertNotIn(b'refs/heads/gone', self.remote.refs())
        error = self.expect('PUSH_REJECTED', self.local.push, self.remote.url, ':refs/heads/gone', BASIC)
        self.assertEqual(error.details['reason'], 'remote ref does not exist')

    def test_a_server_side_rejection(self):
        before = self.remote.refs()
        for refspec in ('HEAD:refs/heads/protected', ':refs/heads/protected',
                        f'+{self.orphan.decode()}:refs/heads/protected'):
            with self.subTest(refspec=refspec):
                error = self.expect('PUSH_REJECTED', self.local.push, self.remote.url, refspec, TOKEN)
                self.assertIn('protected branch', error.message)
        self.assertEqual(self.remote.refs(), before)

    def test_refused(self):
        before = self.remote.refs()
        for credential, status in ((None, 401), (WRONG, 401), (READER, 403)):
            with self.subTest(credential=credential):
                error = self.expect('PUSH_REFUSED', self.local.push, self.remote.url, 'HEAD:refs/heads/main',
                                    credential)
                self.assertEqual(error.details['status'], status)
        self.assertEqual(self.remote.refs(), before)
        self.assertEqual(ra.ls_remote(self.remote.url, READER)['refs/heads/main'], self.c2.decode())

    def test_failed(self):
        self.expect('REMOTE_FAILED', self.local.push, self.remote.url.replace('repo.git', 'none.git'),
                    'HEAD:refs/heads/main', BASIC)
        closed = socket_closed()
        with closed as url:
            self.expect('REMOTE_FAILED', self.local.push, url, 'HEAD:refs/heads/main', BASIC)
        self.assertEqual(closed.accepted, 1)

    def test_refused_input(self):
        for refspec in ('HEAD', 'HEAD:main', 'HEAD:refs/heads/a..b', 'a:b:c', '+:', None):
            with self.subTest(refspec=refspec), self.assertRaises(ValueError):
                self.local.push(self.remote.url, refspec, BASIC)
        self.expect('PUSH_REJECTED', self.local.push, self.remote.url, 'no-such:refs/heads/x', BASIC)
        self.expect('REVISION_INVALID', self.local.push, self.remote.url, 'HEAD@{yesterday}:refs/heads/x', BASIC)
        self.assertEqual(self.remote.requests, [])

    def test_client_hooks_are_refused_before_any_access(self):
        path = local_copy(self.tmp / 'hooked.git')
        hooks = path / 'hooks'
        hooks.mkdir(exist_ok=True)
        (hooks / 'pre-push.sample').write_text('#!/bin/sh\n', encoding='utf-8')
        with ra.open_repository(path, config='repository', work_tree=False, ceilings=[self.tmp]) as repo:
            self.assertIsNone(repo.client_hooks())
            (hooks / 'pre-push').write_text('#!/bin/sh\nexit 1\n', encoding='utf-8')
            error = self.expect('HOOKS_UNSUPPORTED', repo.push, self.remote.url, 'HEAD:refs/heads/main', BASIC)
            self.assertEqual(error.details['hook'], 'hooks/pre-push')
        (hooks / 'pre-push').unlink()
        config = path / 'config'
        config.write_text(config.read_text(encoding='utf-8') + '[core]\n\thooksPath = elsewhere\n', encoding='utf-8')
        for policy in ('none', 'repository'):
            with self.subTest(policy=policy), ra.open_repository(path, config=policy, work_tree=False,
                                                                 ceilings=[self.tmp]) as repo:
                error = self.expect('HOOKS_UNSUPPORTED', repo.push, self.remote.url, 'HEAD:refs/heads/main', BASIC)
                self.assertEqual(error.details['hook'], 'core.hooksPath=elsewhere')
        self.assertEqual(self.remote.requests, [])

    def test_the_credential_goes_to_the_remote_s_origin_only(self):
        transport = ra._transport_modules().Transport('http://127.0.0.1:1/', TOKEN)
        sent = []

        def request(method, url, headers=None, **_kwargs):
            sent.append((url, headers.get('Authorization')))
            raise RuntimeError('stop')

        with mock.patch.object(transport.pool_manager, 'request', side_effect=request):
            for url in ('http://127.0.0.1:1/x/info/refs', 'http://127.0.0.1:2/x/info/refs',
                        'https://127.0.0.1:1/x/info/refs', 'http://localhost:1/x/info/refs'):
                with self.assertRaises(RuntimeError):
                    transport._http_request(url)
        self.assertEqual(sent, [('http://127.0.0.1:1/x/info/refs', TOKEN.authorization()),
                                ('http://127.0.0.1:2/x/info/refs', None), ('https://127.0.0.1:1/x/info/refs', None),
                                ('http://localhost:1/x/info/refs', None)])


class Clone(TransportCase):
    def test_a_bare_clone(self):
        destination = self.tmp / f'{self._testMethodName}.git'
        written = ra.clone(self.remote.url, destination, TOKEN)
        self.assertEqual(written, {'refs/heads/main': self.c2.decode(), 'refs/heads/protected': self.c2.decode(),
                                   'refs/tags/light': self.c1.decode(), 'refs/tags/v1': self.tag.decode()})
        with ra.open_repository(destination, config='repository', work_tree=False, ceilings=[self.tmp]) as repo:
            self.assertTrue(repo.bare)
            self.assertEqual(repo.head(), ra.Head(self.c2.decode(), 'refs/heads/main'))
            self.assertEqual(repo.commit('v1'), self.c1.decode())
            self.assertEqual(repo.blob('main~1', 'a.txt'), b'one\n')
            self.assertEqual(repo.full_name('main'), 'refs/heads/main')
        config = (destination / 'config').read_text(encoding='utf-8')
        self.assertIn(self.remote.url, config)
        self.assertNoSecret(config)
        self.assertEqual(self.headers(), {TOKEN.authorization()})

    def test_refused_and_failed_leave_nothing(self):
        destination = self.tmp / f'{self._testMethodName}.git'
        self.expect('REMOTE_REFUSED', ra.clone, self.remote.url, destination)
        self.assertFalse(destination.exists())
        self.expect('REMOTE_FAILED', ra.clone, self.remote.url.replace('repo.git', 'none.git'), destination, BASIC)
        self.assertFalse(destination.exists())
        destination.mkdir()
        with self.assertRaises(ValueError):
            ra.clone(self.remote.url, destination, BASIC)


if __name__ == '__main__':
    unittest.main()
