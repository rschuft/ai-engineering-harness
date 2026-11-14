"""Every body the broker checks is read strictly (plan leaf S-03.3, fix-forward of the independent security review:
B1, N4, N6).

Run from the repository root, under the tools interpreter:

    <tools python> -I -B -m unittest discover -s integrations/inference/tests -p test_body.py -v

json.loads keeps the last of a repeated key, while a parser upstream may keep the first: a body that repeats a key
could pass the broker's checks as one document and reach the provider as another ("model" twice past the
allowlist; "tools" or a type twice past the reach rule). Shown here: a duplicate key at any depth (escapes decoded)
refused BODY_DUPLICATE_KEY with nothing forwarded, on the inference and the control listener; a top-level key that
case-folds to mcp_servers or container refused PROVIDER_REACH_REFUSED; a Content-Length of digits other than ASCII
refused BODY_LENGTH_INVALID. After the re-review: a body that is not strict UTF-8 without a BOM refused
BODY_ENCODING_INVALID (json.loads alone reads UTF-16, UTF-32 and a BOM), and a header value holding any control
character but HTAB refused HEADER_VALUE_INVALID. The reviewer's probe bodies (probe_admit.py) are reused as data. Everything is synthetic.
"""
from __future__ import annotations

import io
import json
import socket
import unittest

import broker_support as S

CATEGORY = 'integration'
IB = S.IB
FAMILY = 'anthropic-messages'
M = S.MODEL_A
DUPLICATES = {
    'model twice (first unlisted, last allowed)': '{"model":"claude-unlisted-model","model":"%s","messages":[]}' % M,
    'tools twice (first a server tool)': ('{"model":"%s","tools":[{"type":"web_search_20250305","name":"web_search"}],'
                                          '"tools":[],"messages":[]}' % M),
    'a tool type twice (first a server tool)': ('{"model":"%s","tools":[{"type":"web_search_20250305","name":"w",'
                                                '"type":"custom","input_schema":{"type":"object"}}],"messages":[]}' % M),
    'a source type twice (first url)': ('{"model":"%s","messages":[{"role":"user","content":[{"type":"image","source":'
                                        '{"type":"url","url":"https://example.invalid/x.png","type":"base64",'
                                        '"media_type":"image/png","data":"AA=="}}]}]}' % M),
    'a key twice through an escape': '{"model":"x","mod\\u0065l":"%s","messages":[]}' % M,
    'deep in a tool result': ('{"model":"%s","messages":[{"role":"user","content":[{"type":"tool_result",'
                              '"tool_use_id":"t","content":[{"type":"text","text":"a","text":"b"}]}]}]}' % M),
}


class StrictJson(unittest.TestCase):
    def test_a_repeated_key_at_any_depth(self):
        for name, text in DUPLICATES.items():
            with self.subTest(name):
                self.assertEqual(json.loads(text).get('model'), M)     # what json.loads alone reads
                with self.assertRaises(IB.DuplicateKey):
                    IB.strict_json(text)
        self.assertEqual(IB.strict_json(b'{"a":{"b":1},"c":[{"b":2},{"b":3}]}'), {'a': {'b': 1},
                                                                                'c': [{'b': 2}, {'b': 3}]})
        self.assertNotIn('model', str(IB.DuplicateKey('a JSON object repeats a key')))


class OverTheWire(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.upstream = S.FakeUpstream(FAMILY)
        cls.rig = S.Rig(S.component({FAMILY: cls.upstream.origin})).start()

    @classmethod
    def tearDownClass(cls):
        cls.rig.close()
        cls.upstream.close()

    def send(self, grant, data: bytes, extra=()):
        return S.request(self.rig.inference, 'POST', '/v1/messages', raw_body=data,
                         header_pairs=[S.auth(FAMILY, grant['token']), ('Content-Type', 'application/json'),
                                       *extra])

    def test_a_duplicate_key_is_refused_and_nothing_is_forwarded(self):
        grant = self.rig.issue(family=FAMILY)
        before = len(self.upstream.requests)
        for name, text in DUPLICATES.items():
            with self.subTest(name):
                status, _, data = self.send(grant, text.encode())
                self.assertEqual((status, json.loads(data)['aieh_refusal']['code']), (400, 'BODY_DUPLICATE_KEY'))
        self.assertEqual(self.upstream.requests[before:], [])
        self.assertEqual(self.send(grant, ('{"model":"%s","messages":[]}' % M).encode())[0], 200)   # the control

    def test_a_case_folded_reach_key_is_refused(self):
        grant = self.rig.issue(family=FAMILY)
        before = len(self.upstream.requests)
        for key in ('MCP_SERVERS', 'Mcp_Servers', 'CONTAINER', 'Container'):
            with self.subTest(key):
                status, _, data = self.send(grant, json.dumps({'model': M, key: [], 'messages': []}).encode())
                self.assertEqual((status, json.loads(data)['aieh_refusal']['code']), (400, 'PROVIDER_REACH_REFUSED'))
                line = [line for line in self.rig.audit_lines() if line.get('event') == 'request'][-1]
                self.assertEqual(line['reach'], {'rule': 'top-level-key', 'name': key})
        self.assertEqual(self.upstream.requests[before:], [])

    def test_a_content_length_of_other_digits_is_refused(self):
        """'²' and '١٠' are str.isdigit(); int('١٠') is 10. Sent raw (latin-1 '²' on the wire) and socket-free."""
        grant = self.rig.issue(family=FAMILY)
        body = b'{"model":"%s"}' % M.encode()
        connection = socket.create_connection(('127.0.0.1', self.rig.inference), timeout=30)
        try:
            connection.sendall(b'POST /v1/messages HTTP/1.1\r\nHost: 127.0.0.1\r\nx-api-key: ' + grant['token'].encode()
                               + b'\r\nContent-Type: application/json\r\nContent-Length: \xb2\r\n'
                               b'Connection: close\r\n\r\n' + body)
            answer = b''
            while chunk := connection.recv(65536):
                answer += chunk
        finally:
            connection.close()
        self.assertTrue(answer.startswith(b'HTTP/1.1 400'), answer[:80])
        self.assertIn(b'BODY_LENGTH_INVALID', answer)
        for value in ('١٠', '²', ' 1٠'):
            with self.subTest(value=value):
                headers = S.headers(S.auth(FAMILY, grant['token']), ('Content-Type', 'application/json'),
                                    ('Content-Length', value))
                with self.assertRaises(IB.InferenceError) as caught:
                    self.rig.broker.admit('POST', '/v1/messages', headers, io.BytesIO(b'{"model":"x"}' + b' ' * 8).read)
                self.assertEqual(caught.exception.code, 'BODY_LENGTH_INVALID')

    def raw(self, grant, extra_head: bytes, body: bytes) -> tuple:
        """One request written byte for byte; (status, refusal code or None)."""
        connection = socket.create_connection(('127.0.0.1', self.rig.inference), timeout=30)
        try:
            connection.sendall(b'POST /v1/messages HTTP/1.1\r\nHost: 127.0.0.1\r\nx-api-key: ' + grant['token'].encode()
                               + b'\r\nContent-Type: application/json\r\n' + extra_head
                               + b'Content-Length: %d\r\nConnection: close\r\n\r\n' % len(body) + body)
            answer = b''
            while chunk := connection.recv(65536):
                answer += chunk
        finally:
            connection.close()
        status = int(answer.split(b' ', 2)[1])
        return status, json.loads(answer.partition(b'\r\n\r\n')[2])['aieh_refusal']['code'] if status >= 400 else None

    def test_a_body_that_is_not_strict_utf8_without_a_bom_is_refused(self):
        """The re-review: json.loads reads UTF-16, UTF-32 and a UTF-8 BOM, so such a body was admitted. Now only
        strict UTF-8 without a byte order mark is read; nothing else is forwarded."""
        grant = self.rig.issue(family=FAMILY)
        text = '{"model":"%s","messages":[]}' % M
        before = len(self.upstream.requests)
        invalid, not_json = (400, 'BODY_ENCODING_INVALID'), (400, 'BODY_NOT_JSON')
        for name, body, expected in (
                ('UTF-16 LE with a BOM', text.encode('utf-16'), invalid),
                ('UTF-16 BE without a BOM: valid UTF-8 (NUL bytes), then not JSON', text.encode('utf-16-be'),
                 not_json),
                ('UTF-32', text.encode('utf-32'), invalid),
                ('a UTF-8 BOM', b'\xef\xbb\xbf' + text.encode(), invalid),
                ('a surrogate encoded as bytes', text.encode()[:-2] + b'\xed\xa0\x80"]}', invalid),
                ('Latin-1', ('{"model":"%s","messages":[{"role":"user","content":"caf\xe9"}]}' % M)
                 .encode('latin-1'), invalid)):
            with self.subTest(name):
                self.assertEqual(self.raw(grant, b'', body), expected)
        self.assertEqual(self.upstream.requests[before:], [])
        self.assertEqual(self.raw(grant, b'', text.encode()), (200, None))                     # the control
        self.assertEqual(self.raw(grant, b'', ('{"model":"%s","messages":[{"role":"user","content":"café"}]}'
                                               % M).encode('utf-8')), (200, None))
        with self.assertRaises(IB.BodyEncoding):
            IB.strict_json(b'\xef\xbb\xbf{}')

    def test_a_header_value_with_a_control_character_is_refused(self):
        """The re-review: anthropic-beta: a<NUL>b was forwarded. Every control character but HTAB is refused."""
        grant = self.rig.issue(family=FAMILY)
        body = ('{"model":"%s","messages":[]}' % M).encode()
        before = len(self.upstream.requests)
        for byte in [*range(0x00, 0x09), 0x0b, 0x0c, *range(0x0e, 0x20), 0x7f]:
            with self.subTest(byte=hex(byte)):
                status_code = self.raw(grant, b'anthropic-beta: a' + bytes([byte]) + b'b\r\n', body)
                self.assertEqual(status_code, (400, 'HEADER_VALUE_INVALID'))
        self.assertEqual(self.upstream.requests[before:], [])
        self.assertEqual(self.raw(grant, b'anthropic-beta: a\tb\r\n', body), (200, None))       # HTAB is allowed


class Control(unittest.TestCase):
    def test_a_control_body_that_is_not_utf8_is_refused(self):
        rig = S.Rig(S.component({'openai-chat': 'http://127.0.0.1:9'})).start()
        self.addCleanup(rig.close)
        text = ('{"conversation_id":"%s","attempt_id":"%s","family":"openai-chat","models":["%s"],"ttl_s":60}'
                % (S.new_id(), S.new_id(), M))
        for body in (text.encode('utf-16'), b'\xef\xbb\xbf' + text.encode()):
            status, _, data = S.request(rig.control, 'POST', '/v1/grants', raw_body=body,
                                        header_pairs=[('Content-Type', 'application/json')])
            self.assertEqual((status, json.loads(data)['aieh_refusal']['code']), (400, 'CONTROL_BODY_INVALID'))
        self.assertEqual(rig.broker.status()['grants']['live'], 0)

    def test_a_duplicate_key_in_a_control_body_is_refused(self):
        rig = S.Rig(S.component({'openai-chat': 'http://127.0.0.1:9'})).start()
        self.addCleanup(rig.close)
        attempt = S.new_id()
        text = ('{"conversation_id":"%s","attempt_id":"%s","family":"anthropic-messages","family":"openai-chat",'
                '"models":["%s"],"ttl_s":60}' % (S.new_id(), attempt, M)).encode()
        status, _, data = S.request(rig.control, 'POST', '/v1/grants', raw_body=text,
                                    header_pairs=[('Content-Type', 'application/json')])
        self.assertEqual((status, json.loads(data)['aieh_refusal']['code']), (400, 'CONTROL_BODY_INVALID'))
        self.assertEqual(rig.broker.status()['grants']['live'], 0)


if __name__ == '__main__':
    unittest.main()
