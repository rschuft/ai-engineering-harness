"""The Integration process's request checks, in process (plan leaf U-01.3; decision 0025, points 2 to 5).

- Every request needs the Owner UI session credential: the application's route table is walked, and every route
  and method (and paths that are no route) answers ``SESSION_CREDENTIAL_MISSING`` without it. The one exception is
  the CORS preflight, which carries no data: it reads no session, answers no session field and sets no cookie.
- The credential travels in the ``X-AIEH-Owner-Session`` header, never a cookie: no response sets a cookie, and a
  credential in a cookie is not accepted.
- Host and Origin are checked against literals (``HOST_NOT_ALLOWED``, ``ORIGIN_NOT_ALLOWED``) before anything else.
- Missing, foreign, expired and revoked are refused with their codes, and the store's canonical dump is equal before
  and after; no response and no log line holds the credential.
- There is one route, ``POST /session``; no dispatch endpoint.

The application is driven through ASGI on an event loop in this process (no listener; the listener is
test_listener.py's).
"""
from __future__ import annotations

import datetime
import json
import unittest

import ownerhost_support as T

CATEGORY = 'contract'
A, S, E = T.A, T.S, T.E
NOW = T.utc(2026, 11, 16, 12, 0, 0)
METHODS = ('GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS')
NOT_ROUTES = ('/', '/session/', '/sessions', '/api/conversations', '/dispatch', '/health', '/docs', '/openapi.json',
              '/static/index.html', '/%2e%2e/session')


class CountingStore:
    """The conversation store, counting the session lookups the application makes."""

    def __init__(self, store):
        self.store, self.lookups = store, 0

    def session_by_verifier(self, verifier):
        self.lookups += 1
        return self.store.session_by_verifier(verifier)


class Base(unittest.TestCase):
    def setUp(self):
        self.scratch = T.Scratch()
        self.addCleanup(self.scratch.close)
        self.counting = CountingStore(self.scratch.store)
        self.lines = []
        self.clock = T.stamp(NOW)
        self.app = A.create_app(lambda: self.counting, clock=lambda: self.clock, log=self.lines.append)

    def call(self, method, path, *headers, **kw):
        return T.call(self.app, method, path, (T.HOST, *headers), **kw)

    def assert_refused(self, result, status, code):
        got_status, headers, body = result
        self.assertEqual((got_status, T.code_of(body)), (status, code), body[:200])
        self.assertNotIn('set-cookie', dict(headers))


class EveryRequestNeedsTheCredential(Base):
    def routes(self):
        return [(route.path, sorted(route.methods)) for route in self.app.routes]

    def test_the_route_table_is_one_session_route_and_no_dispatch_endpoint(self):
        self.assertEqual(self.routes(), [('/session', ['POST'])])
        self.assertEqual([r.path for r in A.ROUTES], ['/session'])

    def test_every_route_and_method_without_the_credential_is_missing(self):
        self.scratch.enroll(at=NOW)
        paths = [path for path, _ in self.routes()] + list(NOT_ROUTES)
        for path in paths:
            for method in METHODS:
                with self.subTest(method=method, path=path):
                    before = self.scratch.dump()
                    self.assert_refused(self.call(method, path), 401, 'SESSION_CREDENTIAL_MISSING')
                    self.assertEqual(self.scratch.dump(), before)

    def test_every_route_answers_with_the_credential(self):
        credential, record = self.scratch.enroll(at=NOW)
        for path, methods in self.routes():
            for method in methods:
                with self.subTest(method=method, path=path):
                    status, headers, body = self.call(method, path, (S.HEADER, credential))
                    self.assertEqual(status, 200, body)
                    self.assertEqual(json.loads(body), {'sessionId': record.session_id, 'issuedAt': record.issued_at,
                                                        'expiresAt': record.expires_at})
                    self.assertEqual(dict(headers)['cache-control'], 'no-store')
                    self.assertNotIn('set-cookie', dict(headers))
        status, _, body = self.call('GET', '/no-such-route', (S.HEADER, credential))
        self.assertEqual((status, T.code_of(body)), (404, 'NOT_FOUND'))
        self.assertNotIn(b'no-such-route', body)
        status, _, body = self.call('GET', '/session', (S.HEADER, credential))
        self.assertEqual((status, T.code_of(body)), (405, 'METHOD_NOT_ALLOWED'))
        self.assertNotIn(b'/session', body)

    def test_the_preflight_is_the_one_exception_and_carries_no_data(self):
        credential, record = self.scratch.enroll(at=NOW)
        status, headers, body = self.call('OPTIONS', '/session', ('origin', T.SHELL_ORIGIN),
                                          ('access-control-request-method', 'POST'),
                                          ('access-control-request-headers', 'x-aieh-owner-session,content-type'))
        headers = dict(headers)
        self.assertEqual((status, body), (200, b'OK'))
        self.assertEqual(self.counting.lookups, 0, 'the preflight read the session table')
        self.assertEqual(headers['access-control-allow-origin'], T.SHELL_ORIGIN)
        self.assertNotIn('access-control-allow-credentials', headers)
        self.assertNotIn('set-cookie', headers)
        self.assertEqual(sorted(h.strip() for h in headers['access-control-allow-methods'].split(',')),
                         ['GET', 'POST'])
        for text in (record.session_id, record.expires_at, credential):
            self.assertNotIn(text, json.dumps(headers) + body.decode())

    def test_a_preflight_for_another_header_or_from_another_origin_is_refused(self):
        status, _, _ = self.call('OPTIONS', '/session', ('origin', T.SHELL_ORIGIN),
                                 ('access-control-request-method', 'POST'), ('access-control-request-headers', 'cookie'))
        self.assertEqual(status, 400)
        self.assert_refused(self.call('OPTIONS', '/session', ('origin', 'http://127.0.0.1:13300'),
                                      ('access-control-request-method', 'POST')), 403, 'ORIGIN_NOT_ALLOWED')
        self.assertEqual(self.counting.lookups, 0)

    def test_a_websocket_is_refused_without_reaching_a_route(self):
        credential, _ = self.scratch.enroll(at=NOW)
        for headers in ((T.HOST,), (T.HOST, (S.HEADER, credential))):
            self.assertEqual(T.call_websocket(self.app, '/session', headers), [{'type': 'websocket.close',
                                                                               'code': 1008}])
        self.assertEqual(self.counting.lookups, 0)


class HostAndOrigin(Base):
    def test_the_host_must_be_the_literal_address_and_port(self):
        credential, _ = self.scratch.enroll(at=NOW)
        for host in ('localhost:13310', '127.0.0.1', '127.0.0.1:13311', '[::1]:13310', '127.0.0.1:13310.evil.test',
                     'evil.test', '0177.0.0.1:13310', ''):
            with self.subTest(host=host):
                result = T.call(self.app, 'POST', '/session', [('host', host), (S.HEADER, credential)])
                self.assert_refused(result, 400, 'HOST_NOT_ALLOWED')
        self.assert_refused(T.call(self.app, 'POST', '/session', [(S.HEADER, credential)]), 400, 'HOST_NOT_ALLOWED')
        self.assert_refused(T.call(self.app, 'POST', '/session', [T.HOST, T.HOST, (S.HEADER, credential)]), 400,
                            'HOST_NOT_ALLOWED')
        self.assertEqual(self.counting.lookups, 0)

    def test_an_origin_must_be_one_of_the_shell_s_two(self):
        credential, _ = self.scratch.enroll(at=NOW)
        for origin in ('http://127.0.0.1:13300', 'http://localhost:5173', 'https://127.0.0.1:5173', 'null',
                       'http://127.0.0.1:5173/', 'http://evil.test'):
            with self.subTest(origin=origin):
                self.assert_refused(self.call('POST', '/session', ('origin', origin), (S.HEADER, credential)), 403,
                                    'ORIGIN_NOT_ALLOWED')
        for origin in A.SHELL_ORIGINS:
            status, headers, _ = self.call('POST', '/session', ('origin', origin), (S.HEADER, credential))
            self.assertEqual(status, 200)
            self.assertEqual(dict(headers)['access-control-allow-origin'], origin)
            self.assertNotIn('access-control-allow-credentials', dict(headers))
        self.assertEqual(A.SHELL_ORIGINS, ('http://127.0.0.1:4173', 'http://127.0.0.1:5173'))

    def test_a_request_without_origin_from_the_host_itself_is_judged_by_its_credential(self):
        credential, _ = self.scratch.enroll(at=NOW)
        self.assertEqual(self.call('POST', '/session', (S.HEADER, credential))[0], 200)


class Refusals(Base):
    def refused(self, code, *headers):
        before = self.scratch.dump()
        result = self.call('POST', '/session', ('origin', T.SHELL_ORIGIN), *headers)
        self.assert_refused(result, 401, code)
        self.assertEqual(self.scratch.dump(), before, f'{code} changed the store')
        # the browser can read the refusal's code (CORS), and nothing of the request is echoed
        self.assertEqual(dict(result[1])['access-control-allow-origin'], T.SHELL_ORIGIN)
        return result

    def test_missing_foreign_expired_revoked_each_with_its_code_changing_nothing(self):
        old, _ = self.scratch.enroll(at=NOW - datetime.timedelta(days=1))
        expired, _ = self.scratch.enroll(at=NOW - datetime.timedelta(days=1), hours=1)
        outcomes = {}
        for code, headers in (('SESSION_CREDENTIAL_MISSING', ()),
                              ('SESSION_CREDENTIAL_FOREIGN', ((S.HEADER, E.mint()),)),
                              ('SESSION_CREDENTIAL_EXPIRED', ((S.HEADER, expired),)),
                              ('SESSION_CREDENTIAL_REVOKED', ((S.HEADER, old),))):
            with self.subTest(code=code):
                outcomes[code] = self.refused(code, *headers)
        current, _ = self.scratch.enroll(at=NOW)
        self.refused('SESSION_CREDENTIAL_REVOKED', (S.HEADER, expired))
        self.assertEqual(self.call('POST', '/session', (S.HEADER, current))[0], 200)
        for code, (_, headers, body) in outcomes.items():
            text = body.decode() + json.dumps(headers)
            for value in (old, expired, current):
                self.assertNotIn(value, text)

    def test_every_other_inventory_credential_shape_is_refused_as_foreign(self):
        self.scratch.enroll(at=NOW)
        for cid, value in T.samples().items():
            if '\n' in value:          # a PEM key cannot be a header value: refused for its shape in test_session
                continue
            with self.subTest(credential=cid):
                self.refused('SESSION_CREDENTIAL_FOREIGN', (S.HEADER, value))

    def test_a_credential_in_a_cookie_or_another_header_is_not_accepted(self):
        credential, _ = self.scratch.enroll(at=NOW)
        for header in (('cookie', f'X-AIEH-Owner-Session={credential}'), ('authorization', f'Bearer {credential}'),
                       ('x-session-api-key', credential)):
            with self.subTest(header=header[0]):
                self.refused('SESSION_CREDENTIAL_MISSING', header)
        result = self.call('POST', '/session', query=f'credential={credential}'.encode())
        self.assert_refused(result, 401, 'SESSION_CREDENTIAL_MISSING')

    def test_the_log_records_outcomes_and_the_public_session_id_only(self):
        credential, record = self.scratch.enroll(at=NOW)
        self.call('POST', '/session', (S.HEADER, credential))
        self.call('POST', '/session', (S.HEADER, E.mint()))
        self.call('POST', '/session', query=f'c={credential}'.encode())
        self.assertEqual(self.lines, [f'accepted POST /session 200 session={record.session_id}',
                                      'refused SESSION_CREDENTIAL_FOREIGN POST /session',
                                      'refused SESSION_CREDENTIAL_MISSING POST /session'])
        self.assertEqual(T.exposures('\n'.join(self.lines), [credential]), [])

    def test_no_client_path_reaches_the_log(self):
        """A path cannot forge a log line (an encoded line feed) or carry a credential into the log: the log names
        the matched route, or "unmatched", and a common method, or OTHER."""
        credential, record = self.scratch.enroll(at=NOW)
        forged = f'/x\naccepted POST /session 200 session={record.session_id}'
        for method, path, headers in (('GET', forged, ()), ('POST', forged, ((S.HEADER, credential),)),
                                      ('GET', f'/{credential}', ()), ('GET', f'/{credential}', ((S.HEADER, credential),)),
                                      ('BREW', '/session\r\nX', ()), ('POST', '/session', ())):
            self.call(method, path, *headers)
        self.assertEqual(self.lines, ['refused SESSION_CREDENTIAL_MISSING GET unmatched',
                                      f'accepted POST unmatched 404 session={record.session_id}',
                                      'refused SESSION_CREDENTIAL_MISSING GET unmatched',
                                      f'accepted GET unmatched 404 session={record.session_id}',
                                      'refused SESSION_CREDENTIAL_MISSING OTHER unmatched',
                                      'refused SESSION_CREDENTIAL_MISSING POST /session'])
        self.assertTrue(all('\n' not in line and '\r' not in line for line in self.lines))
        self.assertEqual(T.exposures('\n'.join(self.lines), [credential]), [])


if __name__ == '__main__':
    unittest.main()
