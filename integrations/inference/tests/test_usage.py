"""The usage extractors (decision 0015 section 6.1): counts from the final usage-bearing event of a streamed
answer, else from the JSON body; 'unknown' when absent or unreadable. Fed whole and byte by byte.
"""
from __future__ import annotations

import json
import unittest

import broker_support as S

CATEGORY = 'unit'
IB = S.IB


def sse(events) -> bytes:
    return b''.join(((f'event: {name}\n' if name else '') + f'data: {json.dumps(event)}\n\n').encode()
                    for name, event in events)


def read(kind, content_type, data, *, step=None):
    reader = IB.UsageReader(kind, content_type)
    if step is None:
        reader.feed(data)
    else:
        for index in range(0, len(data), step):
            reader.feed(data[index:index + step])
    return reader.finish()


EXPECTED = {'input': 11, 'output': 7, 'total': 18}


class TestStreamed(unittest.TestCase):
    def test_each_family_reads_its_final_usage_event_whole_and_byte_by_byte(self):
        for family in S.FAMILIES:
            data = sse(S.usage_events(family)) + (b'' if family == 'anthropic-messages' else b'data: [DONE]\n\n')
            for step in (None, 1, 7):
                with self.subTest(family=family, step=step):
                    self.assertEqual(read(family, 'text/event-stream; charset=utf-8', data, step=step), EXPECTED)

    def test_without_a_usage_event_it_is_unknown(self):
        for family in S.FAMILIES:
            with self.subTest(family=family):
                self.assertEqual(read(family, 'text/event-stream', sse(S.usage_events(family, with_usage=False))),
                                 'unknown')

    def test_anthropic_cache_counts_and_input_from_the_final_event(self):
        events = [('message_start', {'type': 'message_start', 'message': {'usage': {
                      'input_tokens': 5, 'cache_read_input_tokens': 100, 'cache_creation_input_tokens': 20}}}),
                  ('message_delta', {'type': 'message_delta', 'usage': {'output_tokens': 9, 'input_tokens': 6}})]
        self.assertEqual(read('anthropic-messages', 'text/event-stream', sse(events)),
                         {'input': 126, 'output': 9, 'total': 135})

    def test_anthropic_without_input_counts_is_unknown(self):
        events = [('message_delta', {'type': 'message_delta', 'usage': {'output_tokens': 9}})]
        self.assertEqual(read('anthropic-messages', 'text/event-stream', sse(events)), 'unknown')

    def test_crlf_lines_multi_line_data_and_comments(self):
        first, second = '{"id": "x",', '"usage": {"prompt_tokens": 3, "completion_tokens": 4}}'
        crlf = '\r\n'
        data = f': keep-alive{crlf}id: 1{crlf}data: {first}{crlf}data:{second}{crlf}{crlf}'.encode()
        self.assertEqual(read('openai-chat', 'text/event-stream', data), {'input': 3, 'output': 4, 'total': 7})

    def test_a_last_event_without_a_blank_line_is_still_read(self):
        event = json.dumps({'usage': {'prompt_tokens': 1, 'completion_tokens': 2, 'total_tokens': 3}})
        self.assertEqual(read('openai-chat', 'text/event-stream', f'data: {event}'.encode()),
                         {'input': 1, 'output': 2, 'total': 3})

    def test_an_overlong_line_makes_it_unknown_and_holds_nothing_more(self):
        reader = IB.UsageReader('openai-chat', 'text/event-stream')
        reader.feed(b'data: ' + b'x' * (IB.SSE_LINE_LIMIT + 1))
        reader.feed(sse(S.usage_events('openai-chat')))
        self.assertEqual(len(reader.buffer), 0)
        self.assertEqual(reader.finish(), 'unknown')

    def test_usage_read_before_an_overflow_is_not_trusted(self):
        reader = IB.UsageReader('openai-chat', 'text/event-stream')
        reader.feed(sse(S.usage_events('openai-chat')))
        reader.feed(b'data: ' + b'x' * (IB.SSE_LINE_LIMIT + 1))
        self.assertEqual(reader.finish(), 'unknown')


class TestJsonBodies(unittest.TestCase):
    def test_each_family_reads_its_body(self):
        for family in S.FAMILIES:
            data = json.dumps(S.json_answer(family)).encode()
            with self.subTest(family=family):
                self.assertEqual(read(family, 'application/json', data, step=5), EXPECTED)
                self.assertEqual(read(family, None, data), EXPECTED)

    def test_absent_unreadable_or_malformed_usage_is_unknown(self):
        for family in S.FAMILIES:
            with self.subTest(family=family):
                self.assertEqual(read(family, 'application/json',
                                      json.dumps(S.json_answer(family, with_usage=False)).encode()), 'unknown')
                self.assertEqual(read(family, 'application/json', b'{not json'), 'unknown')
                self.assertEqual(read(family, 'application/json', b'[1, 2]'), 'unknown')
                self.assertEqual(read(family, 'application/json', b''), 'unknown')
        for usage in ({'prompt_tokens': True, 'completion_tokens': 1}, {'prompt_tokens': -1, 'completion_tokens': 1},
                      {'prompt_tokens': '1', 'completion_tokens': 1}, {'prompt_tokens': 1}):
            with self.subTest(usage=usage):
                self.assertEqual(read('openai-chat', 'application/json', json.dumps({'usage': usage}).encode()),
                                 'unknown')

    def test_a_pretty_printed_body_is_read_whole(self):
        for family in S.FAMILIES:
            data = json.dumps(S.json_answer(family), indent=2).encode()
            with self.subTest(family=family):
                self.assertEqual(read(family, 'application/json', data, step=3), EXPECTED)

    def test_total_falls_back_to_the_sum(self):
        body = json.dumps({'usage': {'input_tokens': 2, 'output_tokens': 3}}).encode()
        self.assertEqual(read('openai-responses', 'application/json', body), {'input': 2, 'output': 3, 'total': 5})

    def test_an_oversized_body_is_unknown(self):
        reader = IB.UsageReader('openai-chat', 'application/json')
        reader.feed(b' ' * (IB.USAGE_BODY_LIMIT + 1))
        reader.feed(json.dumps(S.json_answer('openai-chat')).encode())
        self.assertEqual(len(reader.buffer), 0)
        self.assertEqual(reader.finish(), 'unknown')

    def test_an_unknown_extractor_is_refused(self):
        with self.assertRaises(ValueError):
            IB.UsageReader('litellm', 'application/json')


if __name__ == '__main__':
    unittest.main()
