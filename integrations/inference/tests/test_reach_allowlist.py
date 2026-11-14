"""Provider-side reach by allowlist (plan leaf S-03.3, fix-forward of the independent security review: S2).

Run from the repository root, under the tools interpreter:

    <tools python> -I -B -m unittest discover -s integrations/inference/tests -p test_reach_allowlist.py -v

The reach rule refused named things (url and file sources, container_upload): a source of another type (web_page)
or a replayed server_tool_use block passed. Now, for anthropic-messages, a content block (messages[].content, system
when it is a list, and the content of a tool_result, a search_result or a source of type content) is admitted only
with one of CONTENT_BLOCK_TYPES, and a block's source only with one of SOURCE_TYPES; everything else is
PROVIDER_REACH_REFUSED, nothing forwarded. After the re-review a source is checked only where the provider interprets
it (a content block): a tool's input_schema and a tool_use's input are opaque and admitted. The reviewer's probe bodies (probe_admit.py) are reused as data.
Everything is synthetic.
"""
from __future__ import annotations

import json
import unittest

import broker_support as S

CATEGORY = 'integration'
IB = S.IB
FAMILY = 'anthropic-messages'


URL_IMAGE = {'type': 'image', 'source': {'type': 'url', 'url': 'https://e.invalid/a.png'}}


def user(*blocks) -> dict:
    return {'model': S.MODEL_A, 'messages': [{'role': 'user', 'content': list(blocks)}]}


def assistant(*blocks) -> dict:
    return {'model': S.MODEL_A, 'messages': [{'role': 'assistant', 'content': list(blocks)}]}


def tool_result(*blocks) -> dict:
    return user({'type': 'tool_result', 'tool_use_id': 'toolu_1', 'content': list(blocks)})


REFUSED = {
    'a web_page source (probe)': (user({'type': 'document', 'source': {'type': 'web_page', 'url': 'https://x.invalid'}}),
                                  ('source-type', 'web_page')),
    'a server_tool_use block replayed (probe)': (assistant({'type': 'server_tool_use', 'id': 'srvtoolu_1',
                                                            'name': 'web_fetch', 'input': {'url': 'https://x.invalid'}}),
                                                 ('block-type', 'server_tool_use')),
    'a web search result': (assistant({'type': 'web_search_tool_result', 'tool_use_id': 'srvtoolu_1', 'content': []}),
                            ('block-type', 'web_search_tool_result')),
    'a code execution result': (assistant({'type': 'code_execution_tool_result', 'tool_use_id': 's', 'content': {}}),
                                ('block-type', 'code_execution_tool_result')),
    'an mcp_tool_use block': (assistant({'type': 'mcp_tool_use', 'id': 'm', 'name': 'n', 'server_name': 's',
                                         'input': {}}), ('block-type', 'mcp_tool_use')),
    'a container_upload block': (user({'type': 'container_upload', 'file_id': 'file_1'}),
                                 ('block-type', 'container_upload')),
    'a type not yet known': (user({'type': 'something_new', 'text': 'x'}), ('block-type', 'something_new')),
    'a block without a type': (user({'text': 'x'}), ('block-type', None)),
    'a block that is not an object': (user('x'), ('content-shape', 'content')),
    'content that is an object': ({'model': S.MODEL_A, 'messages': [{'role': 'user', 'content': {'type': 'text'}}]},
                                  ('content-shape', 'content')),
    'in a tool result': (tool_result({'type': 'text', 'text': 'a'}, {'type': 'server_tool_use', 'id': 's', 'name': 'n',
                                                                    'input': {}}), ('block-type', 'server_tool_use')),
    'in a search result': (tool_result({'type': 'search_result', 'source': 's', 'title': 't', 'content': [
        {'type': 'mcp_tool_use', 'id': 'm', 'name': 'n', 'server_name': 's', 'input': {}}]}),
        ('block-type', 'mcp_tool_use')),
    'in a content source': (user({'type': 'document', 'source': {'type': 'content', 'content': [
        {'type': 'web_fetch_tool_result', 'tool_use_id': 's', 'content': {}}]}}), ('block-type', 'web_fetch_tool_result')),
    'in the system list': ({'model': S.MODEL_A, 'system': [{'type': 'text', 'text': 's'},
                                                           {'type': 'server_tool_use', 'id': 's', 'name': 'n',
                                                            'input': {}}], 'messages': []},
                           ('block-type', 'server_tool_use')),
    'a url source': (user({'type': 'image', 'source': {'type': 'url', 'url': 'https://x.invalid/a.png'}}),
                     ('source-type', 'url')),
    'a file source': (user({'type': 'document', 'source': {'type': 'file', 'file_id': 'file_1'}}),
                      ('source-type', 'file')),
    'a source without a type': (user({'type': 'image', 'source': {'url': 'https://x.invalid/a.png'}}),
                                ('source-type', None)),
    'an image whose source is not an object': (user({'type': 'image', 'source': 'https://x.invalid/a.png'}),
                                               ('source-type', None)),
    # the reviewer's delta check (probe_admit3.py): shapes the position-only check admitted and forwarded
    'a case-variant Messages beside messages': ({'model': S.MODEL_A, 'messages': [], 'Messages': [
        {'role': 'user', 'content': [URL_IMAGE]}]}, ('top-level-key', 'Messages')),
    'a case-variant System list': ({'model': S.MODEL_A, 'System': [URL_IMAGE], 'messages': []},
                                   ('top-level-key', 'System')),
    'a case-variant Tools list': ({'model': S.MODEL_A, 'Tools': [{'type': 'web_search_20250305', 'name': 'w'}],
                                   'messages': []}, ('top-level-key', 'Tools')),
    'messages as an object': ({'model': S.MODEL_A, 'messages': {'0': {'role': 'user', 'content': [URL_IMAGE]}}},
                              ('messages-shape', 'messages')),
    'a message given as a list': ({'model': S.MODEL_A, 'messages': [[{'role': 'user', 'content': [URL_IMAGE]}]]},
                                  ('messages-shape', 'messages')),
    'a url image under an unknown top-level key': ({'model': S.MODEL_A, 'messages': [], 'extra': [URL_IMAGE]},
                                                   ('source-type', 'url')),
    'system as an object': ({'model': S.MODEL_A, 'system': {'type': 'text', 'text': 's'}, 'messages': []},
                            ('system-shape', 'system')),
    'a system list holding a string': ({'model': S.MODEL_A, 'system': ['s'], 'messages': []},
                                       ('system-shape', 'system')),
    'a url source beside a tool, outside its input_schema': ({'model': S.MODEL_A, 'tools': [
        {'name': 't', 'input_schema': {'type': 'object'}, 'extra': {'source': {'type': 'url', 'url': 'x'}}}],
        'messages': []}, ('source-type', 'url')),
    'a url source in a tool_use, outside its input': (assistant({'type': 'tool_use', 'id': 't', 'name': 'x',
                                                                'input': {}, 'cache_control': {'source': {
                                                                    'type': 'url'}}}), ('source-type', 'url')),
    'a url source in a nested tool result':(tool_result({'type': 'tool_result', 'tool_use_id': 't2', 'content': [
        {'type': 'image', 'source': {'type': 'url', 'url': 'https://x.invalid/a.png'}}]}), ('source-type', 'url')),
}

ADMITTED = {
    'text, thinking and redacted thinking': assistant({'type': 'thinking', 'thinking': 't', 'signature': 's'},
                                                      {'type': 'redacted_thinking', 'data': 'd'},
                                                      {'type': 'text', 'text': 'x'}),
    'a tool use and its result': user({'type': 'tool_result', 'tool_use_id': 't', 'content': [
        {'type': 'text', 'text': 'x'}, {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png',
                                                                      'data': 'AA=='}}]}),
    'a text and a content document': user({'type': 'document', 'source': {'type': 'text', 'media_type': 'text/plain',
                                                                           'data': 'x'}},
                                          {'type': 'document', 'source': {'type': 'content', 'content': [
                                              {'type': 'text', 'text': 'x'}]}}),
    'a search result': tool_result({'type': 'search_result', 'source': 'https://s.test', 'title': 't',
                                    'content': [{'type': 'text', 'text': 'x'}]}),
    'string contents': {'model': S.MODEL_A, 'system': 's', 'messages': [{'role': 'user', 'content': 'x'}]},
    # the re-review's ruling: a source is checked only where the provider interprets it (a content block); a tool's
    # input_schema and a tool_use's input are opaque to the provider and never read
    'a tool schema with a property named source': {'model': S.MODEL_A, 'tools': [{
        'name': 'Clone', 'description': 'd', 'input_schema': {'type': 'object', 'properties': {
            'source': {'type': 'string'}, 'nested': {'type': 'object', 'properties': {'source': {'type': 'url'}}}}}}],
        'messages': [{'role': 'user', 'content': 'x'}]},
    'a tool use whose input holds a source': assistant({'type': 'tool_use', 'id': 't', 'name': 'Clone',
                                                        'input': {'source': {'type': 'git', 'url': 'x'}}}),
    'a tool use whose input holds a url source': assistant({'type': 'tool_use', 'id': 't', 'name': 'Fetch', 'input': {
        'source': {'type': 'url', 'url': 'https://x.invalid'}, 'blocks': [{'type': 'container_upload'}]}}),
    'a search result whose source is its citation string': tool_result({'type': 'search_result', 'source': 'https://s',
                                                                        'title': 't', 'content': []}),
}


class TheChecker(unittest.TestCase):
    def test_each_refused_shape(self):
        for name, (document, expected) in REFUSED.items():
            with self.subTest(name):
                self.assertEqual(IB.anthropic_reach(document), expected)

    def test_each_admitted_shape(self):
        for name, document in ADMITTED.items():
            with self.subTest(name):
                self.assertIsNone(IB.anthropic_reach(document))

    def test_the_allowlists(self):
        self.assertEqual(IB.CONTENT_BLOCK_TYPES, ('text', 'image', 'document', 'tool_use', 'tool_result', 'thinking',
                                                  'redacted_thinking', 'search_result'))
        self.assertEqual(IB.SOURCE_TYPES, ('base64', 'text', 'content'))


class OverTheWire(unittest.TestCase):
    def test_refused_with_nothing_forwarded_and_admitted_forwarded(self):
        upstream = S.FakeUpstream(FAMILY)
        self.addCleanup(upstream.close)
        rig = S.Rig(S.component({FAMILY: upstream.origin})).start()
        self.addCleanup(rig.close)
        grant = rig.issue(family=FAMILY)
        for name, (document, (rule, found)) in REFUSED.items():
            with self.subTest(name):
                status, _, data = S.request(rig.inference, 'POST', '/v1/messages', document,
                                            [S.auth(FAMILY, grant['token'])])
                self.assertEqual((status, json.loads(data)['aieh_refusal']['code']), (400, 'PROVIDER_REACH_REFUSED'))
                line = [line for line in rig.audit_lines() if line.get('event') == 'request'][-1]
                self.assertEqual(line['reach'], {'rule': rule, 'name': found})
        self.assertEqual(upstream.requests, [])
        for name, document in ADMITTED.items():
            with self.subTest(name):
                status, _, _ = S.request(rig.inference, 'POST', '/v1/messages', document,
                                         [S.auth(FAMILY, grant['token'])])
                self.assertEqual(status, 200)
        self.assertEqual(len(upstream.requests), len(ADMITTED))


if __name__ == '__main__':
    unittest.main()
