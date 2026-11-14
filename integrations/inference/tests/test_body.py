"""Every body the broker checks is read strictly (plan leaf S-03.3, fix-forward of the independent security review:
B1, N4, N6).

Run from the repository root, under the tools interpreter:

    <tools python> -I -B -m unittest discover -s integrations/inference/tests -p test_body.py -v

json.loads keeps the last of a repeated key, while a parser upstream may keep the first: a body that repeats a key
could pass the broker's checks as one document and reach the provider as another ("model" twice past the
allowlist; "tools" or a type twice past the reach rule). Shown here: a duplicate key at any depth (escapes decoded)
refused BODY_DUPLICATE_KEY with nothing forwarded, on the inference and the control listener; a top-level key that
case-folds to mcp_servers or container refused PROVIDER_REACH_REFUSED; a Content-Length of digits other than ASCII
refused BODY_LENGTH_INVALID. The reviewer's probe bodies (probe_admit.py) are reused as data. Everything is synthetic.
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


class Control(unittest.TestCase):
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
