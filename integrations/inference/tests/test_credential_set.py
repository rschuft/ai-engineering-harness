"""The provider key's set command (decision 0015 section 2.1): the key is read from standard input only and
stored as the F-06.3 entry "AIEH model provider" (user = the provider id) under an aieh-credential-act/1
receipt with fingerprints only. An in-memory credential provider and a fixture integration store only:
nothing here reads, writes, deletes or enumerates the real Credential Manager.
"""
from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import broker_support as S

CATEGORY = 'unit'
IB = S.IB
OTHER_KEY = 'synthetic-rotated-key-NOT-A-REAL-CREDENTIAL-99aa'


class Stdin:
    """Standard input as a pipe (bytes), or a terminal."""

    def __init__(self, data: bytes, tty: bool = False):
        self.buffer, self.tty, self.reads = io.BytesIO(data), tty, 0

    def isatty(self):
        return self.tty


class Unreadable(Stdin):
    def __init__(self):
        super().__init__(b'')

    @property
    def buffer(self):
        raise AssertionError('standard input was read')

    @buffer.setter
    def buffer(self, value):
        pass


class StoreFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-inference-cred-'))
        self.store = S.STORE.open_store(self.tmp / 'integration.sqlite')

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def receipt(self, key):
        record = self.store.get(key)
        return json.loads(record.intent_json), self.store.events(key)


class TestReadKey(unittest.TestCase):
    def test_exactly_the_key_with_an_optional_newline(self):
        for data in (S.KEY.encode(), S.KEY.encode() + b'\n', S.KEY.encode() + b'\r\n'):
            with self.subTest(data=data[-2:]):
                self.assertEqual(IB.read_key(Stdin(data)), S.KEY)

    def test_each_refusal(self):
        self.assertEqual(self.code(Stdin(S.KEY.encode(), tty=True)), 'KEY_STDIN_TTY')
        for data in (b'', b'\n', b'short', S.KEY.encode() + b'\n\n', b' ' + S.KEY.encode(),
                     S.KEY.encode()[:10] + b' ' + S.KEY.encode()[10:], 'synthetic-kéy-value'.encode(),
                     b'\xff\xfe' * 8, b'x' * 4097, b'synthetic\tkey-value'):
            with self.subTest(length=len(data)):
                self.assertEqual(self.code(Stdin(data)), 'KEY_INVALID')

    def code(self, stream):
        with self.assertRaises(IB.InferenceError) as caught:
            IB.read_key(stream)
        return caught.exception.code


class TestCredentialSet(StoreFixture):
    def test_provision_then_rotate_with_fingerprints_only(self):
        provider, guard = S.MemoryProvider(), IB.BrokerGuard()
        report = IB.credential_set(provider, self.store, S.PROVIDER, S.KEY, guard=guard)
        self.assertEqual(provider.entries, {'AIEH model provider': (S.PROVIDER, S.KEY)})
        self.assertEqual((report['format'], report['verb'], report['entry'], report['user'],
                          report['fingerprint'], report['fingerprint_before']),
                         ('aieh-inference-credential-set/1', 'provision', 'AIEH model provider', S.PROVIDER,
                          IB.contract.fingerprint(S.KEY), None))
        intent, events = self.receipt(report['receipt']['operation_key'])
        self.assertEqual((intent['format'], intent['verb'], intent['service'], intent['entry'], intent['user'],
                          intent['trigger']),
                         ('aieh-credential-act/1', 'provision', 'inference-broker', 'AIEH model provider', S.PROVIDER,
                          'owner direction'))
        self.assertEqual([e.to_state for e in events], ['reserved', 'dispatched', 'confirmed'])
        rotated = IB.credential_set(provider, self.store, 'synthetic-second', OTHER_KEY, guard=guard)
        self.assertEqual((rotated['verb'], rotated['fingerprint_before'], rotated['fingerprint']),
                         ('rotate', IB.contract.fingerprint(S.KEY), IB.contract.fingerprint(OTHER_KEY)))
        self.assertEqual(provider.entries, {'AIEH model provider': ('synthetic-second', OTHER_KEY)})
        intent, events = self.receipt(rotated['receipt']['operation_key'])
        self.assertEqual(json.loads(events[-1].detail_json)['previous_user'], S.PROVIDER)
        everything = self.store.canonical_dump().decode('utf-8', 'replace') + json.dumps([report, rotated])
        self.assertNotIn(S.KEY, everything)
        self.assertNotIn(OTHER_KEY, everything)

    def test_a_key_that_does_not_read_back_leaves_an_unknown_receipt(self):
        class Lossy(S.MemoryProvider):
            def set(self, name, user, secret, comment=''):
                super().set(name, user, secret[:-1], comment)
        with self.assertRaises(IB.InferenceError) as caught:
            IB.credential_set(Lossy(), self.store, S.PROVIDER, S.KEY, guard=IB.BrokerGuard())
        self.assertEqual((caught.exception.code, caught.exception.refusal), ('KEY_READ_BACK_FAILED', False))
        (attempt,) = self.store.attempts()
        self.assertEqual(attempt.state, 'unknown')

    def test_an_invalid_provider_id_changes_nothing(self):
        provider = S.MemoryProvider()
        for provider_id in ('Synthetic', '', 'a b', 5, '-x'):
            with self.subTest(provider_id=provider_id):
                with self.assertRaises(IB.InferenceError) as caught:
                    IB.credential_set(provider, self.store, provider_id, S.KEY, guard=IB.BrokerGuard())
                self.assertEqual(caught.exception.code, 'PROVIDER_ID_INVALID')
        self.assertEqual((provider.entries, self.store.attempts()), ({}, []))


class TestCommand(StoreFixture):
    def context(self, stdin, provider):
        def refuse(*args):
            raise AssertionError('credential-set touched the logs or served')
        stores = []

        def store():
            stores.append(S.STORE.open_store(self.tmp / 'integration.sqlite'))
            return stores[-1]
        return IB.Context(component=lambda: None, provider=lambda: provider, store=store, logs=refuse, stdin=stdin,
                          out=io.StringIO(), err=io.StringIO(), wait=refuse)

    def test_the_key_comes_from_standard_input_and_only_its_fingerprint_is_shown(self):
        provider = S.MemoryProvider()
        ctx = self.context(Stdin(S.KEY.encode() + b'\n'), provider)
        self.assertEqual(IB.main(['credential-set', '--provider', S.PROVIDER], ctx), 0)
        report = json.loads(ctx.out.getvalue())
        self.assertEqual(report['fingerprint'], IB.contract.fingerprint(S.KEY))
        self.assertEqual(provider.entries['AIEH model provider'], (S.PROVIDER, S.KEY))
        self.assertNotIn(S.KEY, ctx.out.getvalue() + ctx.err.getvalue())
        self.assertIn('I7 no-exposure scan: clean', ctx.err.getvalue())

    def test_refusals_exit_2_and_a_bad_provider_id_reads_no_key(self):
        provider = S.MemoryProvider()
        ctx = self.context(Unreadable(), provider)
        self.assertEqual(IB.main(['credential-set', '--provider', 'Bad Id'], ctx), 2)
        self.assertIn('PROVIDER_ID_INVALID', ctx.err.getvalue())
        ctx = self.context(Stdin(S.KEY.encode(), tty=True), provider)
        self.assertEqual(IB.main(['credential-set', '--provider', S.PROVIDER], ctx), 2)
        self.assertIn('KEY_STDIN_TTY', ctx.err.getvalue())
        self.assertEqual(provider.entries, {})

    def test_output_that_would_hold_the_key_is_withheld(self):
        class Leaky(S.MemoryProvider):
            def get(self, name):
                raise RuntimeError(f'backend echoed {S.KEY}')
        ctx = self.context(Stdin(S.KEY.encode()), Leaky())
        self.assertEqual(IB.main(['credential-set', '--provider', S.PROVIDER], ctx), 1)
        self.assertIn('EXPOSURE_FOUND', ctx.err.getvalue())
        self.assertNotIn(S.KEY, ctx.out.getvalue() + ctx.err.getvalue())

    def test_the_key_has_no_command_line_option(self):
        with self.assertRaises(SystemExit):
            with unittest.mock.patch('sys.stderr', io.StringIO()):
                IB.main(['credential-set', '--provider', S.PROVIDER, '--key', S.KEY], self.context(Unreadable(),
                                                                                                    S.MemoryProvider()))


if __name__ == '__main__':
    unittest.main()
