"""A family forwards only the request headers it declares (plan leaf S-03.3, fix-forward of the independent security
review: S1).

Run from the repository root, under the tools interpreter:

    <tools python> -I -B -m unittest discover -s integrations/inference/tests -p test_headers.py -v

The broker's request headers were a deny list: anything not named on it reached the provider (an underscore
spelling of an account-scope header, a method-override header, a declared encoding or charset). Now each family
declares in families.json the header names and name prefixes it forwards; every other header is stripped and named
in the audit (stripped_headers), and the declarations are validated (none may name or cover a header the broker never
forwards, or an account-scope header). Refused before anything is forwarded: a header value holding a CR or LF
(obsolete line folding included, HEADER_VALUE_INVALID), a Content-Encoding other than identity
(CONTENT_ENCODING_REFUSED), and a Content-Type other than one application/json with at most charset=utf-8, or none
on a request with a body (CONTENT_TYPE_REFUSED). The reviewer's probe requests (probe_admit.py) are reused as data.
Everything is synthetic.
"""
from __future__ import annotations

import copy
import json
import shutil
import socket
import tempfile
import unittest
from pathlib import Path

import broker_support as S

CATEGORY = 'integration'
IB = S.IB
ANTHROPIC = {'names': ['accept', 'anthropic-beta', 'anthropic-version', 'content-type', 'user-agent', 'x-app'],
             'prefixes': ['x-stainless-']}
OPENAI = {'names': ['accept', 'content-type', 'openai-beta', 'user-agent'], 'prefixes': ['x-stainless-']}
UNDECLARED = tuple((name, f'undeclared-value-{index}') for index, name in enumerate((
    'anthropic_workspace_id', 'X-HTTP-Method-Override', 'X-Original-URL', 'X-Forwarded-Host', 'Cookie',
    'Openai-Organization', 'Anthropic-Dangerous-Direct-Browser-Access', 'X-Synthetic')))


def raw_send(port: int, head: bytes, body: bytes) -> bytes:
    """One request written byte for byte (what http.client would not send); the whole answer."""
    connection = socket.create_connection(('127.0.0.1', port), timeout=30)
    try:
        connection.sendall(head + b'Content-Length: %d\r\nConnection: close\r\n\r\n' % len(body) + body)
        answer = b''
        while chunk := connection.recv(65536):
            answer += chunk
        return answer
    finally:
        connection.close()


class Declarations(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-headers-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_the_shipped_allowlists(self):
        families = IB.load_declarations()
        described = {f.id: f.describe()['headers'] for f in families.values()}
        self.assertEqual(described, {'anthropic-messages': ANTHROPIC, 'openai-responses': OPENAI,
                                     'openai-chat': OPENAI})
        anthropic = families['anthropic-messages']
        for name in ('content-type', 'anthropic-version', 'x-stainless-retry-count', 'x-app'):
            self.assertTrue(anthropic.forwards(name), name)
        for name in ('anthropic-workspace-id', 'anthropic_workspace_id', 'x-api-key', 'authorization', 'cookie',
                     'x-http-method-override', 'openai-beta', 'x-stainless'):
            self.assertFalse(anthropic.forwards(name), name)

    def test_a_declaration_that_names_or_covers_what_is_never_forwarded_is_refused(self):
        original = json.loads(IB.FAMILIES_PATH.read_text(encoding='utf-8'))
        for name, headers in {
                'a credential header': {'names': ['content-type', 'x-api-key'], 'prefixes': []},
                'authorization': {'names': ['authorization'], 'prefixes': []},
                'cookie': {'names': ['cookie'], 'prefixes': []},
                'host': {'names': ['host'], 'prefixes': []},
                'accept-encoding': {'names': ['accept-encoding'], 'prefixes': []},
                'an account-scope name': {'names': ['anthropic-workspace-id'], 'prefixes': []},
                'a prefix covering the account scope': {'names': ['accept'], 'prefixes': ['anthropic-']},
                'a prefix under the account scope': {'names': ['accept'], 'prefixes': ['anthropic-workspace-']},
                'a prefix covering x-api-key': {'names': ['accept'], 'prefixes': ['x-']},
                'a prefix covering x-forwarded-for': {'names': ['accept'], 'prefixes': ['x-forwarded-']},
                'a prefix not ending with -': {'names': ['accept'], 'prefixes': ['x-stainless']},
                'an upper-case name': {'names': ['Accept'], 'prefixes': []},
                'no names': {'names': [], 'prefixes': []},
                'a duplicate': {'names': ['accept', 'accept'], 'prefixes': []},
                'names not a list': {'names': 'accept', 'prefixes': []},
                'an extra key': {'names': ['accept'], 'prefixes': [], 'all': True},
                'no prefixes key': {'names': ['accept']}}.items():
            with self.subTest(name):
                data = copy.deepcopy(original)
                data['families'][0]['headers'] = headers
                path = self.tmp / 'families.json'
                path.write_text(json.dumps(data), encoding='utf-8')
                with self.assertRaises(IB.InferenceError) as caught:
                    IB.load_declarations(path)
                self.assertEqual(caught.exception.code, 'DECLARATION_INVALID')
        data = copy.deepcopy(original)
        del data['families'][0]['headers']
        path = self.tmp / 'families.json'
        path.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaises(IB.InferenceError):
            IB.load_declarations(path)


class OverTheWire(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.upstreams = {family: S.FakeUpstream(family) for family in S.FAMILIES}
        cls.rig = S.Rig(S.component({family: fake.origin for family, fake in cls.upstreams.items()})).start()

    @classmethod
    def tearDownClass(cls):
        cls.rig.close()
        for fake in cls.upstreams.values():
            fake.close()

    def last_line(self):
        return [line for line in self.rig.audit_lines() if line.get('event') == 'request'][-1]

    def test_only_declared_headers_reach_the_upstream(self):
        for family in S.FAMILIES:
            with self.subTest(family):
                grant = self.rig.issue(family=family)
                declared = ANTHROPIC if family == 'anthropic-messages' else OPENAI
                sent = [('Accept', 'application/json'), ('User-Agent', 'synthetic/1'),
                        ('X-Stainless-Retry-Count', '0'), ('Anthropic-Version', '2023-06-01'),
                        ('OpenAI-Beta', 'assistants=v2'), ('X-App', 'cli'), *UNDECLARED]
                upstream = self.upstreams[family]
                before = len(upstream.requests)
                status, _, _ = S.request(self.rig.inference, 'POST', S.ROUTE[family], {'model': S.MODEL_A},
                                         [S.auth(family, grant['token']), *sent])
                self.assertEqual(status, 200)
                (received,) = upstream.requests[before:]
                names = {name.lower() for name, _ in received['headers']}
                broker_set = {'host', 'content-length', 'accept-encoding', IB.load_declarations()[family].auth_header}
                allowed = set(declared['names'])
                self.assertEqual(names - broker_set - allowed,
                                 {n for n in names if n.startswith('x-stainless-')})
                self.assertIn('x-stainless-retry-count', names)
                expected_kept = {'accept', 'user-agent', 'content-type'} | (
                    {'anthropic-version', 'x-app'} if family == 'anthropic-messages' else {'openai-beta'})
                self.assertEqual(names & (allowed | {'x-stainless-retry-count'}), expected_kept | {
                    'x-stainless-retry-count'})
                for name, value in UNDECLARED:
                    self.assertNotIn(name.lower(), names)
                    self.assertNotIn(value, json.dumps(received['headers']))
                member = self.last_line()['stripped_headers']
                stripped = set(member['names'])
                short = {name.lower() for name, _ in UNDECLARED if len(name) <= 32}
                self.assertTrue(short <= stripped, stripped)
                self.assertEqual(member['unrecorded'], 1)       # the one name outside the audit's grammar
                self.assertNotIn('host', stripped)
                self.assertNotIn('content-length', stripped)

    def refused(self, head_extra: bytes, body: bytes, family='anthropic-messages'):
        grant = self.rig.issue(family=family)
        upstream = self.upstreams[family]
        before = len(upstream.requests)
        auth = b'x-api-key: ' + grant['token'].encode() + b'\r\n'
        answer = raw_send(self.rig.inference, b'POST /v1/messages HTTP/1.1\r\nHost: 127.0.0.1\r\n' + auth + head_extra,
                          body)
        self.assertEqual(upstream.requests[before:], [])                     # nothing forwarded
        status = int(answer.split(b' ', 2)[1])
        code = json.loads(answer.partition(b'\r\n\r\n')[2])['aieh_refusal']['code'] if status >= 400 else None
        return status, code

    def test_the_refused_shapes(self):
        body = json.dumps({'model': S.MODEL_A}).encode()
        json_type = b'Content-Type: application/json\r\n'
        for name, head, expected in (
                ('a folded header carrying an account header',
                 json_type + b'X-Synthetic: a\r\n anthropic-workspace-id: wrkspc_Y\r\n', (400, 'HEADER_VALUE_INVALID')),
                ('a folded allowed header', json_type + b'User-Agent: a\r\n\tb\r\n', (400, 'HEADER_VALUE_INVALID')),
                ('deflate', json_type + b'Content-Encoding: deflate\r\n', (415, 'CONTENT_ENCODING_REFUSED')),
                ('gzip', json_type + b'Content-Encoding: gzip\r\n', (415, 'CONTENT_ENCODING_REFUSED')),
                ('two encodings', json_type + b'Content-Encoding: identity\r\nContent-Encoding: identity\r\n',
                 (415, 'CONTENT_ENCODING_REFUSED')),
                ('utf-7', b'Content-Type: application/json; charset=utf-7\r\n', (415, 'CONTENT_TYPE_REFUSED')),
                ('text/plain', b'Content-Type: text/plain\r\n', (415, 'CONTENT_TYPE_REFUSED')),
                ('a second parameter', b'Content-Type: application/json; charset=utf-8; x=1\r\n',
                 (415, 'CONTENT_TYPE_REFUSED')),
                ('a quoted charset', b'Content-Type: application/json; charset="utf-8"\r\n',
                 (415, 'CONTENT_TYPE_REFUSED')),
                ('two types', json_type + json_type, (415, 'CONTENT_TYPE_REFUSED')),
                ('none with a body', b'', (415, 'CONTENT_TYPE_REFUSED'))):
            with self.subTest(name):
                self.assertEqual(self.refused(head, body), expected)

    def test_the_admitted_shapes(self):
        body = json.dumps({'model': S.MODEL_A}).encode()
        for name, head in (('json', b'Content-Type: application/json\r\n'),
                           ('json with utf-8, any case', b'Content-Type: Application/JSON; Charset=UTF-8\r\n'),
                           ('identity', b'Content-Type: application/json\r\nContent-Encoding: identity\r\n')):
            with self.subTest(name):
                grant = self.rig.issue(family='anthropic-messages')
                answer = raw_send(self.rig.inference, b'POST /v1/messages HTTP/1.1\r\nHost: 127.0.0.1\r\nx-api-key: '
                                  + grant['token'].encode() + b'\r\n' + head, body)
                self.assertTrue(answer.startswith(b'HTTP/1.1 200'), answer[:200])

    def test_every_new_code_has_its_status(self):
        self.assertEqual({code: IB.CODES[code][0] for code in ('HEADER_VALUE_INVALID', 'CONTENT_ENCODING_REFUSED',
                                                               'CONTENT_TYPE_REFUSED')},
                         {'HEADER_VALUE_INVALID': 400, 'CONTENT_ENCODING_REFUSED': 415, 'CONTENT_TYPE_REFUSED': 415})


if __name__ == '__main__':
    unittest.main()
