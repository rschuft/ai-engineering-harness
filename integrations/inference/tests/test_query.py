"""Exact query-string equality (plan leaf S-03.3, fix-forward before the first paid call; the OA-12 package section 1
row P and section 5 item 3).

Run from the repository root, under the tools interpreter:

    <tools python> -I -B -m unittest discover -s integrations/inference/tests -p test_query.py -v

A family's query rule was refuse or pass; pass is retired. A family declares refuse or an exact, finite set of
whole query strings, and a request target's raw query (the bytes after its first ?) is admitted only when it is
byte-equal to one of them: no parsing, decoding, reordering or case folding. anthropic-messages declares exactly
beta=true. Shown here: the shipped declarations; beta=true admitted and forwarded unchanged; every other form
refused QUERY_NOT_ALLOWED before anything is sent upstream (over the wire, so the target is what the listener
received); a target without ? admitted as before, a bare ? refused; the families' description output; the
qualification's fake upstream answering the declared query as the broker admits it. Everything is synthetic.
"""
from __future__ import annotations

import io
import json
import unittest

import broker_support as S

CATEGORY = 'integration'
IB = S.IB
IQ = S._load('aieh_inference_qualification', S.HERE.parent / 'inference_qualification.py')
FAMILY = 'anthropic-messages'
REFUSED = ('beta=TRUE', 'Beta=true', 'beta=true&beta=true', 'beta=true&x=1', 'x=1&beta=true', 'beta=%74rue',
           'beta%3Dtrue', 'x=1', 'beta=true&', '&beta=true', 'beta=true#', 'beta=true#x', 'beta=true;', 'beta',
           'beta=', 'beta=true?', 'beta=tru', 'beta=truee', '', '?beta=true', 'beta=true%00')


class Declarations(unittest.TestCase):
    def test_anthropic_messages_declares_exactly_beta_true(self):
        families = IB.load_declarations()
        self.assertEqual(families[FAMILY].query, frozenset({'beta=true'}))
        self.assertEqual({f.id: f.query_rule() for f in families.values()},
                         {'anthropic-messages': ['beta=true'], 'openai-responses': 'refuse', 'openai-chat': 'refuse'})
        raw = json.loads(IB.FAMILIES_PATH.read_text(encoding='utf-8'))
        self.assertNotIn('pass', json.dumps([f['query'] for f in raw['families']]))

    def test_the_description_output_carries_the_rule(self):
        out, err = io.StringIO(), io.StringIO()
        ctx = IB.Context(component=lambda: None, provider=None, store=None, logs=None, stdin=None, out=out, err=err,
                         wait=None)
        self.assertEqual(IB.main(['config'], ctx), 0, err.getvalue())
        described = {f['id']: f['query'] for f in json.loads(out.getvalue())['families']}
        self.assertEqual(described, {'anthropic-messages': ['beta=true'], 'openai-responses': 'refuse',
                                     'openai-chat': 'refuse'})

    def test_admits_query_is_byte_equality(self):
        family = IB.load_declarations()[FAMILY]
        self.assertTrue(family.admits_query('beta=true'))
        for query in REFUSED:
            with self.subTest(query=query):
                self.assertFalse(family.admits_query(query))
        refusing = IB.load_declarations()['openai-chat']
        self.assertFalse(refusing.admits_query('beta=true'))
        self.assertFalse(refusing.admits_query(''))

    def test_the_remedy_names_the_rule(self):
        remedy = IB.REMEDIES['QUERY_NOT_ALLOWED']
        self.assertIn('beta=true', remedy)
        self.assertIn('exactly', remedy)


class OverTheWire(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.upstreams = {family: S.FakeUpstream(family) for family in (FAMILY, 'openai-chat')}
        cls.rig = S.Rig(S.component({family: fake.origin for family, fake in cls.upstreams.items()})).start()

    @classmethod
    def tearDownClass(cls):
        cls.rig.close()
        for fake in cls.upstreams.values():
            fake.close()

    def send(self, grant, target, family=FAMILY):
        return S.request(self.rig.inference, 'POST', target, {'model': S.MODEL_A}, [S.auth(family, grant['token'])])

    def test_beta_true_is_admitted_and_forwarded_unchanged(self):
        grant = self.rig.issue(family=FAMILY)
        upstream = self.upstreams[FAMILY]
        before = len(upstream.requests)
        self.assertEqual(self.send(grant, '/v1/messages?beta=true')[0], 200)
        self.assertEqual(self.send(grant, '/v1/messages')[0], 200)          # no ?: admitted as before
        self.assertEqual([r['path'] for r in upstream.requests[before:]], ['/v1/messages?beta=true', '/v1/messages'])

    def test_every_other_form_is_refused_before_anything_is_sent(self):
        grant = self.rig.issue(family=FAMILY)
        upstream = self.upstreams[FAMILY]
        before = len(upstream.requests)
        for query in REFUSED:
            with self.subTest(query=query):
                status, _, data = self.send(grant, '/v1/messages?' + query)
                self.assertEqual((status, json.loads(data)['aieh_refusal']['code']), (400, 'QUERY_NOT_ALLOWED'))
        self.assertEqual(upstream.requests[before:], [])
        held = self.rig.broker._by_fingerprint[grant['token_fingerprint']]
        self.assertEqual((held.requests, held.refused), (0, len(REFUSED)))

    def test_a_family_that_refuses_queries_refuses_beta_true(self):
        grant = self.rig.issue(family='openai-chat')
        for target in ('/v1/chat/completions?beta=true', '/v1/chat/completions?'):
            with self.subTest(target=target):
                status, _, data = self.send(grant, target, 'openai-chat')
                self.assertEqual((status, json.loads(data)['aieh_refusal']['code']), (400, 'QUERY_NOT_ALLOWED'))
        self.assertEqual(self.send(grant, '/v1/chat/completions', 'openai-chat')[0], 200)
        self.assertEqual([r['path'] for r in self.upstreams['openai-chat'].requests], ['/v1/chat/completions'])


class TheQualificationFakeUpstream(unittest.TestCase):
    def test_it_answers_the_declared_query_as_the_broker_admits_it(self):
        family = IB.load_declarations()[FAMILY]
        sink = io.StringIO()
        fake = IQ.FakeUpstream(family, '127.0.0.1', 0, sink)
        fake.start()
        try:
            statuses = [S.request(fake.port, 'POST', target, {'model': 'syn-main-model'})[0]
                        for target in ('/v1/messages', '/v1/messages?beta=true', '/v1/messages?beta=TRUE',
                                       '/v1/messages?')]
        finally:
            fake.stop()
        self.assertEqual(statuses, [200, 200, 404, 404])
        records = [json.loads(line) for line in sink.getvalue().splitlines()]
        self.assertEqual([r['path'] for r in records], ['/v1/messages', '/v1/messages', None, None])


if __name__ == '__main__':
    unittest.main()
