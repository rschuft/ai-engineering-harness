"""The serve command end to end in this process (never the managed context): the configuration, the provider
key read from an in-memory credential provider, the fixture integration store and audit directory, both
listeners on ephemeral 127.0.0.1 ports, one issued token and one passed-through request to a fake upstream,
then the stop. Its start receipt records the provider key's fingerprint once; its report holds no secret.
"""
from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import broker_support as S

CATEGORY = 'integration'
IB = S.IB


class TestServe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.upstream = S.FakeUpstream('anthropic-messages')

    @classmethod
    def tearDownClass(cls):
        cls.upstream.close()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-inference-serve-'))
        (self.tmp / 'logs').mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def context(self, raw, provider, wait):
        return IB.Context(component=lambda: raw, provider=lambda: provider,
                          store=lambda: S.STORE.open_store(self.tmp / 'integration.sqlite'),
                          logs=lambda: self.tmp / 'logs', stdin=None, out=io.StringIO(), err=io.StringIO(),
                          wait=wait, allow_ephemeral=True)

    def test_serve_issues_passes_through_and_stops(self):
        seen = {}

        def wait(broker):
            rig = type('Ports', (), {'control': broker.listeners['control']['port']})
            status, grant = S.control(rig, 'POST', '/v1/grants', {
                'conversation_id': S.new_id(), 'attempt_id': S.new_id(), 'family': 'anthropic-messages',
                'models': [S.MODEL_A], 'budget': {'requests': 2, 'tokens': 100}, 'ttl_s': 60})
            seen['grant'] = grant
            seen['answer'] = S.request(broker.listeners['inference']['port'], 'POST', '/v1/messages',
                                       {'model': S.MODEL_A, 'stream': True}, [('x-api-key', grant['token'])])
        raw = S.component({'anthropic-messages': self.upstream.origin})
        ctx = self.context(raw, S.MemoryProvider({'AIEH model provider': (S.PROVIDER, S.KEY)}), wait)
        self.assertEqual(IB.main(['serve'], ctx), 0, ctx.err.getvalue())
        self.assertEqual(seen['answer'][0], 200)
        self.assertEqual(self.upstream.requests[-1]['headers'][-1], ('x-api-key', S.KEY))
        report = json.loads(ctx.out.getvalue())
        self.assertEqual(report['provider_key'], {'provider': S.PROVIDER, 'source': 'memory-fake',
                                                  'fingerprint': IB.contract.fingerprint(S.KEY)})
        self.assertEqual(report['grants'], {'live': 1, 'revoked': 0, 'receipts_pending': 0})
        output = ctx.out.getvalue() + ctx.err.getvalue()
        self.assertNotIn(S.KEY, output)
        self.assertNotIn(seen['grant']['token'], output)
        (audit,) = (self.tmp / 'logs').glob('audit-*.jsonl')
        events = [json.loads(line)['event'] for line in audit.read_text(encoding='utf-8').splitlines()]
        self.assertEqual(events, ['broker-start', 'request', 'broker-stop'])
        store = S.STORE.open_store(self.tmp / 'integration.sqlite')
        try:
            starts = [a for a in store.attempts() if a.operation_key.startswith('inference/broker-start/')]
            (start,) = starts
            intent = json.loads(start.intent_json)
            self.assertEqual(intent['provider_key'], {'entry': 'AIEH model provider', 'provider': S.PROVIDER,
                                                      'fingerprint': IB.contract.fingerprint(S.KEY),
                                                      'source': 'memory-fake'})
            self.assertEqual(intent['listeners']['inference']['address'], '127.0.0.1')
            self.assertNotIn(S.KEY, store.canonical_dump().decode('utf-8', 'replace'))
        finally:
            store.close()

    def test_without_ports_or_with_a_bad_configuration_nothing_starts(self):
        def refuse(*args):
            raise AssertionError('serve went past its configuration')
        for raw, code in (({'families': {}}, 'CONFIG_INCOMPLETE'),
                          ({'control_port': 0, 'inference_port': 0, 'api_key': 'x'}, 'CONFIG_SECRET_SHAPED_KEY')):
            with self.subTest(code=code):
                ctx = IB.Context(component=lambda: raw, provider=refuse, store=refuse, logs=refuse, stdin=None,
                                 out=io.StringIO(), err=io.StringIO(), wait=refuse, allow_ephemeral=True)
                self.assertEqual(IB.main(['serve'], ctx), 2)
                self.assertIn(code, ctx.err.getvalue())

    def test_a_start_that_fails_is_reported_and_serves_nothing(self):
        def refuse(*args):
            raise AssertionError('serve waited on a broker that did not start')

        class Failing:
            def __getattr__(self, name):
                raise S.STORE.StoreError('synthetic store failure')
        raw = S.component({'anthropic-messages': self.upstream.origin})
        provider = S.MemoryProvider({'AIEH model provider': (S.PROVIDER, S.KEY)})
        ctx = IB.Context(component=lambda: raw, provider=lambda: provider, store=Failing,
                         logs=lambda: self.tmp / 'logs', stdin=None, out=io.StringIO(), err=io.StringIO(),
                         wait=refuse, allow_ephemeral=True)
        self.assertEqual(IB.main(['serve'], ctx), 1)
        self.assertIn('JOURNAL_FAILED', ctx.err.getvalue())
        ctx.logs = lambda: self.tmp / 'absent'
        ctx.err = io.StringIO()
        self.assertEqual(IB.main(['serve'], ctx), 1)
        self.assertIn('FileNotFoundError', ctx.err.getvalue())
        self.assertNotIn(S.KEY, ctx.err.getvalue())

    def test_without_a_provider_entry_the_keyed_family_is_not_ready(self):
        statuses = {}

        def wait(broker):
            statuses.update(broker.status())
        raw = S.component({'anthropic-messages': self.upstream.origin})
        ctx = self.context(raw, S.MemoryProvider(), wait)
        self.assertEqual(IB.main(['serve'], ctx), 0, ctx.err.getvalue())
        self.assertIsNone(statuses['provider_key'])
        ready = {f['id']: f['not_ready'] for f in statuses['families']}
        self.assertEqual(ready['anthropic-messages'], "the key of provider 'synthetic-provider' is not loaded")


if __name__ == '__main__':
    unittest.main()
