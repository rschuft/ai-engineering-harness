"""Provider-side reach refused (plan leaf S-03.3, fix-forward before the first paid call; the OA-12 package section 3
point 5 and section 5 item 2).

Run from the repository root, under the tools interpreter:

    <tools python> -I -B -m unittest discover -s integrations/inference/tests -p test_reach.py -v

The authorized D1 scope is plain model calls: an anthropic-messages request must not ask the provider to reach or
run anything outside the request. Shown here, on the parsed JSON body of every admitted request: a top-level
mcp_servers or container refused whatever its value; a tool whose type is present and not custom refused (every
server tool and provider-defined tool type); a source of type url or file and a container_upload block refused
anywhere in the body, tool results included; a tools value that is not a list, or a tools entry that is not an
object, refused as tools-shape (fail closed); custom tools and plain content admitted; the audit line naming the
rule and the key or type name in the bounded name grammar, never a value; nothing sent upstream. A body nested too
deeply for the JSON parser (RecursionError) refused BODY_NOT_JSON over the wire, with nothing forwarded and no
handler error, and so is a control body (CONTROL_BODY_INVALID); an upstream answer nested so deeply is unknown
usage, not a handler error. A family with no
reach checker (the OpenAI families) refused at start when its upstream is not loopback (FAMILY_REACH_UNCHECKED),
and unchanged on a loopback upstream. Everything is synthetic.
"""
from __future__ import annotations

import io
import json
import unittest

import broker_support as S
import envelope_support as V

CATEGORY = 'unit'
IB = S.IB
FAMILY = 'anthropic-messages'


def body(**members) -> dict:
    return {'model': S.MODEL_A, 'max_tokens': 16, 'messages': [{'role': 'user', 'content': S.PROMPT_MARKER}],
            **members}


def message(*blocks) -> dict:
    return body(messages=[{'role': 'user', 'content': list(blocks)}])


CUSTOM_TOOL = {'name': 'Read', 'description': 'read a file', 'input_schema': {
    'type': 'object', 'properties': {'file_path': {'type': 'string'}}, 'required': ['file_path']}}

REFUSED = {
    # top-level keys, present at all, any value
    'mcp_servers': (body(mcp_servers=[{'type': 'url', 'url': 'https://mcp.example.test', 'name': 'x'}]),
                    'top-level-key', 'mcp_servers'),
    'mcp_servers empty': (body(mcp_servers=[]), 'top-level-key', 'mcp_servers'),
    'mcp_servers null': (body(mcp_servers=None), 'top-level-key', 'mcp_servers'),
    'container': (body(container='container_011'), 'top-level-key', 'container'),
    'container null': (body(container=None), 'top-level-key', 'container'),
    # tools whose type is present and not custom
    'web search': (body(tools=[{'type': 'web_search_20250305', 'name': 'web_search'}]), 'tool-type',
                   'web_search_20250305'),
    'web fetch': (body(tools=[CUSTOM_TOOL, {'type': 'web_fetch_20250910', 'name': 'web_fetch'}]), 'tool-type',
                  'web_fetch_20250910'),
    'code execution': (body(tools=[{'type': 'code_execution_20250825', 'name': 'code_execution'}]), 'tool-type',
                       'code_execution_20250825'),
    'a provider-defined client tool': (body(tools=[{'type': 'bash_20250124', 'name': 'bash'}]), 'tool-type',
                                       'bash_20250124'),
    'an unknown type': (body(tools=[{'type': 'something_new_20270101', 'name': 'n'}]), 'tool-type',
                        'something_new_20270101'),
    'a type that is not a string': (body(tools=[{'type': None, 'name': 'n'}]), 'tool-type', None),
    'a type outside the grammar': (body(tools=[{'type': 'x' * 40, 'name': 'n'}]), 'tool-type', None),
    # tools whose shape the rule cannot read (fail closed)
    'tools an object': (body(tools={'type': 'web_search_20250305', 'name': 'web_search'}), 'tools-shape', 'tools'),
    'tools a string': (body(tools='web_search_20250305'), 'tools-shape', 'tools'),
    'tools null': (body(tools=None), 'tools-shape', 'tools'),
    'tools a number': (body(tools=1), 'tools-shape', 'tools'),
    'a tools entry a string': (body(tools=[CUSTOM_TOOL, 'web_search_20250305']), 'tools-shape', 'tools'),
    'a tools entry null': (body(tools=[None]), 'tools-shape', 'tools'),
    'a tools entry a list': (body(tools=[[{'type': 'web_search_20250305', 'name': 'web_search'}]]), 'tools-shape',
                             'tools'),
    # sources and blocks, anywhere
    'an image by url': (message({'type': 'image', 'source': {'type': 'url', 'url': 'https://img.example.test/a.png'}}),
                        'source-type', 'url'),
    'a document by url': (message({'type': 'document', 'source': {'type': 'url', 'url': 'https://d.test/a.pdf'}}),
                          'source-type', 'url'),
    'a document by file': (message({'type': 'document', 'source': {'type': 'file', 'file_id': 'file_011'}}),
                           'source-type', 'file'),
    'a container upload': (message({'type': 'container_upload', 'file_id': 'file_011'}), 'block-type',
                           'container_upload'),
    'in a tool result': (message({'type': 'tool_result', 'tool_use_id': 'toolu_1', 'content': [
        {'type': 'text', 'text': 'see image'},
        {'type': 'image', 'source': {'type': 'url', 'url': 'https://img.example.test/b.png'}}]}),
        'source-type', 'url'),
    'deeply nested': (message({'type': 'tool_result', 'tool_use_id': 'toolu_1', 'content': [
        {'type': 'search_result', 'source': 'https://s.test', 'title': 't', 'content': [
            {'type': 'document', 'source': {'type': 'file', 'file_id': 'file_022'}}]}]}),
        'source-type', 'file'),
    'in the system prompt': (body(system=[{'type': 'text', 'text': 's'},
                                          {'type': 'container_upload', 'file_id': 'file_033'}]),
                             'block-type', 'container_upload'),
}

ADMITTED = {
    'plain text': body(),
    'custom tools without a type': body(tools=[CUSTOM_TOOL]),
    'no tools at all': body(tools=[]),
    'a custom tool with its type': body(tools=[{**CUSTOM_TOOL, 'type': 'custom'}]),
    'an image inline': message({'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png',
                                                             'data': 'iVBORw0KGgo='}}),
    'a document as text': message({'type': 'document', 'source': {'type': 'text', 'media_type': 'text/plain',
                                                                  'data': 'plain'}}),
    'a source string, not an object': message({'type': 'search_result', 'source': 'https://s.test', 'title': 't',
                                               'content': [{'type': 'text', 'text': 'x'}]}),
    'the words in text': body(messages=[{'role': 'user', 'content':
                                         'mcp_servers container url file container_upload web_search'}]),
    'a tool use and its result': message({'type': 'tool_use', 'id': 'toolu_1', 'name': 'Read',
                                          'input': {'file_path': 'a.txt'}},
                                         {'type': 'tool_result', 'tool_use_id': 'toolu_1', 'content': 'text'}),
    'metadata and thinking': body(metadata={'user_id': 'u-1'}, thinking={'type': 'enabled', 'budget_tokens': 1024}),
}


class TheChecker(unittest.TestCase):
    def test_each_reach_is_found_with_its_rule_and_name(self):
        for name, (document, rule, found) in REFUSED.items():
            with self.subTest(name):
                got = IB.anthropic_reach(document)
                self.assertIsNotNone(got)
                self.assertEqual(got[0], rule)
                if found is not None:
                    self.assertEqual(got[1], found)

    def test_plain_model_calls_are_not_reach(self):
        for name, document in ADMITTED.items():
            with self.subTest(name):
                self.assertIsNone(IB.anthropic_reach(document))

    def test_the_walk_has_no_recursion_limit(self):
        nested = {'type': 'text', 'text': 'x'}
        for _ in range(5000):
            nested = {'content': [nested]}
        self.assertIsNone(IB.anthropic_reach({'model': S.MODEL_A, 'messages': [nested]}))
        nested['content'].append({'type': 'image', 'source': {'type': 'url', 'url': 'https://x.test'}})
        self.assertEqual(IB.anthropic_reach({'model': S.MODEL_A, 'messages': [nested]}), ('source-type', 'url'))

    def test_only_anthropic_messages_has_a_checker(self):
        self.assertEqual(set(IB.REACH_CHECKERS), {'anthropic-messages'})


class Admission(unittest.TestCase):
    """Socket-free admission on a broker whose upstreams are loopback (connect must not be reached)."""

    @classmethod
    def setUpClass(cls):
        cls.rig = S.Rig(S.component({family: 'http://127.0.0.1:9' for family in S.FAMILIES}), connect=never)
        cls.broker = cls.rig.broker

    @classmethod
    def tearDownClass(cls):
        cls.rig.close()

    def admit(self, grant, document, family=FAMILY):
        data = json.dumps(document).encode()
        headers = S.headers(S.auth(family, grant['token']), ('Content-Type', 'application/json'),
                            ('Content-Length', str(len(data))))
        return self.broker.admit('POST', S.ROUTE[family], headers, io.BytesIO(data).read)

    def test_each_reach_is_refused_and_counted(self):
        grant = self.rig.issue(family=FAMILY)
        for name, (document, rule, found) in REFUSED.items():
            with self.subTest(name):
                with self.assertRaises(IB.InferenceError) as caught:
                    self.admit(grant, document)
                exc = caught.exception
                self.assertEqual((exc.code, exc.status), ('PROVIDER_REACH_REFUSED', 400))
                self.assertEqual(exc.audit, {'reach': {'rule': rule, 'name': found}})
        held = self.broker._by_fingerprint[grant['token_fingerprint']]
        self.assertEqual((held.requests, held.refused), (0, len(REFUSED)))

    def test_plain_model_calls_are_admitted(self):
        grant = self.rig.issue(family=FAMILY)
        for name, document in ADMITTED.items():
            with self.subTest(name):
                self.assertEqual(self.admit(grant, document).model, S.MODEL_A)

    def test_the_openai_families_are_not_checked_on_a_loopback_upstream(self):
        """Their bodies have other shapes; the families serve a loopback upstream only (FAMILY_REACH_UNCHECKED)."""
        for family in ('openai-responses', 'openai-chat'):
            with self.subTest(family):
                grant = self.rig.issue(family=family)
                self.assertEqual(self.admit(grant, body(mcp_servers=[], container='c'), family).model, S.MODEL_A)


def never(*args, **kwargs):
    raise AssertionError('admission reached the upstream connector')


class OverTheWire(unittest.TestCase):
    def test_the_refusal_its_audit_line_and_nothing_upstream(self):
        upstream = S.FakeUpstream(FAMILY)
        self.addCleanup(upstream.close)
        rig = S.Rig(S.component({FAMILY: upstream.origin})).start()
        self.addCleanup(rig.close)
        grant = rig.issue(family=FAMILY)
        secret_url = 'https://img.example.test/SYNTHETIC-VALUE-9f3a.png'
        for document, stream in ((message({'type': 'image', 'source': {'type': 'url', 'url': secret_url}}), False),
                                 (body(tools=[{'type': 'web_search_20250305', 'name': 'web_search'}], stream=True),
                                  True)):
            status, _, data = S.request(rig.inference, 'POST', '/v1/messages', document,
                                        [S.auth(FAMILY, grant['token'])])
            self.assertEqual((status, json.loads(data)['aieh_refusal']['code']), (400, 'PROVIDER_REACH_REFUSED'))
            self.assertNotIn(secret_url, data.decode())
        self.assertEqual(upstream.requests, [])
        status, _, _ = S.request(rig.inference, 'POST', '/v1/messages', body(tools=[CUSTOM_TOOL]),
                                 [S.auth(FAMILY, grant['token'])])
        self.assertEqual(status, 200)
        self.assertEqual(len(upstream.requests), 1)
        lines = [line for line in rig.audit_lines() if line.get('event') == 'request']
        self.assertEqual([(line['code'], line.get('reach')) for line in lines], [
            ('PROVIDER_REACH_REFUSED', {'rule': 'source-type', 'name': 'url'}),
            ('PROVIDER_REACH_REFUSED', {'rule': 'tool-type', 'name': 'web_search_20250305'}),
            (None, None)])
        self.assertNotIn('reach', lines[-1])                       # only a reach refusal carries the member
        self.assertNotIn('SYNTHETIC-VALUE-9f3a', rig.audit.path.read_text(encoding='utf-8'))


def nested(depth: int) -> bytes:
    """A JSON object holding one list nested DEPTH deep: valid JSON that json.loads cannot parse without
    exceeding the interpreter's recursion limit (RecursionError) when DEPTH is large."""
    return b'{"model": "%s", "messages": ' % S.MODEL_A.encode() + b'[' * depth + b']' * depth + b'}'


class TooDeeplyNested(unittest.TestCase):
    """json.loads raises RecursionError, not ValueError, on a body nested deeper than the interpreter's recursion
    limit: admission refuses it BODY_NOT_JSON (never a handler error) and forwards nothing."""

    DEPTH = 200_000

    def test_the_parser_raises_recursion_error_on_it(self):
        with self.assertRaises(RecursionError):
            json.loads(nested(self.DEPTH))
        self.assertEqual(json.loads(nested(3))['messages'], [[[]]])

    def test_admission_refuses_it_socket_free(self):
        rig = S.Rig(S.component({FAMILY: 'http://127.0.0.1:9'}), connect=never)
        self.addCleanup(rig.close)
        grant = rig.issue(family=FAMILY)
        data = nested(self.DEPTH)
        headers = S.headers(S.auth(FAMILY, grant['token']), ('Content-Type', 'application/json'),
                            ('Content-Length', str(len(data))))
        with self.assertRaises(IB.InferenceError) as caught:
            rig.broker.admit('POST', '/v1/messages', headers, io.BytesIO(data).read)
        self.assertEqual((caught.exception.code, caught.exception.status), ('BODY_NOT_JSON', 400))
        self.assertEqual(rig.broker.observed_request('/v1/messages', data)['model'], None)

    def test_over_the_wire_it_is_refused_and_nothing_is_forwarded(self):
        upstream = S.FakeUpstream(FAMILY)
        self.addCleanup(upstream.close)
        rig = S.Rig(S.component({FAMILY: upstream.origin})).start()
        self.addCleanup(rig.close)
        grant = rig.issue(family=FAMILY)
        status, _, data = S.request(rig.inference, 'POST', '/v1/messages', header_pairs=[
            S.auth(FAMILY, grant['token']), ('Content-Type', 'application/json')], raw_body=nested(self.DEPTH))
        self.assertEqual((status, json.loads(data)['aieh_refusal']['code']), (400, 'BODY_NOT_JSON'))
        self.assertEqual(upstream.requests, [])
        lines = rig.audit_lines()
        self.assertEqual([line['code'] for line in lines if line.get('event') == 'request'], ['BODY_NOT_JSON'])
        self.assertEqual([line for line in lines if line.get('event') == 'handler-error'], [])
        status, _, _ = S.request(rig.inference, 'POST', '/v1/messages', body(), [S.auth(FAMILY, grant['token'])])
        self.assertEqual(status, 200)                        # the broker serves on
        self.assertEqual(len(upstream.requests), 1)

    def test_a_control_body_nested_too_deeply_is_refused(self):
        rig = S.Rig(S.component({FAMILY: 'http://127.0.0.1:9'}), connect=never).start()
        self.addCleanup(rig.close)
        data = b'[' * 30_000 + b']' * 30_000          # within the control body limit (64 KiB)
        self.assertLessEqual(len(data), IB.CONTROL_BODY_LIMIT)
        status, _, answer = S.request(rig.control, 'POST', '/v1/grants', header_pairs=[
            ('Content-Type', 'application/json')], raw_body=data)
        self.assertEqual((status, json.loads(answer)['aieh_refusal']['code']), (400, 'CONTROL_BODY_INVALID'))
        self.assertEqual([line for line in rig.audit_lines() if line.get('event') == 'handler-error'], [])

    def test_an_upstream_answer_nested_too_deeply_is_unknown_usage(self):
        for content_type, data in (('application/json', nested(self.DEPTH)),
                                   ('text/event-stream', b'data: ' + nested(self.DEPTH) + b'\n\n')):
            with self.subTest(content_type):
                reader = IB.UsageReader(FAMILY, content_type)
                reader.feed(data)
                self.assertEqual(reader.finish(), 'unknown')


class AtStart(V.EnvelopeCase):
    """A family with no reach checker and an upstream that is not loopback is refused at start, before the provider
    key is read or a listener opens; on a loopback upstream it starts as before."""

    def refused_at_start(self, family):
        raw = V.component(family=family)
        self.confirmed(raw)                       # the envelope is authorized: only the missing checker refuses
        self.assertStartRefused(raw, 'FAMILY_REACH_UNCHECKED')

    def test_openai_responses_bound_to_the_envelope_is_refused_at_start(self):
        self.refused_at_start('openai-responses')

    def test_openai_chat_bound_to_the_envelope_is_refused_at_start(self):
        self.refused_at_start('openai-chat')

    def test_beside_anthropic_messages_too(self):
        raw = V.component(others={'openai-chat': {'provider': S.PROVIDER, 'upstream': V.ORIGIN,
                                                  'models': [S.MODEL_A]}})
        self.confirmed(raw)
        self.assertStartRefused(raw, 'FAMILY_REACH_UNCHECKED')

    def test_the_broker_itself_refuses_to_start_one(self):
        raw = V.component(family='openai-chat')
        self.confirmed(raw)
        rig = V.BoundRig(raw, V.minted(raw, self.db), connect=V.refuse, db=self.db)
        self.addCleanup(rig.close)
        with self.assertRaises(IB.InferenceError) as caught:
            rig.broker.start()
        self.assertEqual(caught.exception.code, 'FAMILY_REACH_UNCHECKED')
        self.assertEqual(rig.broker.listeners, {})

    def test_loopback_upstreams_start_as_before(self):
        IB.check_reach(IB.load_config(S.component({family: 'http://127.0.0.1:9' for family in S.FAMILIES}),
                                      allow_ephemeral=True))
        IB.check_reach(IB.load_config(V.component(), allow_ephemeral=True))     # anthropic-messages, bound


if __name__ == '__main__':
    unittest.main()
