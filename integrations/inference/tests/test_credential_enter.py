"""The Owner's key-entry command (plan leaf S-03.3; the OA-12 package's act 2 and section 5 item 4, the architect's
conditions): inference_broker.py credential-enter.

Run from the repository root, under the tools interpreter:

    <tools python> -I -B -m unittest discover -s integrations/inference/tests -p test_credential_enter.py -v

Shown: it runs only on an interactive console, refused before any prompt otherwise (KEY_CONSOLE_REQUIRED; the real
check, stdin_is_console, on a pipe, a file and a stream without a descriptor); the key is read once at a hidden
prompt (an injected console reader: never a real console; getpass's echoing fallback refused); every rule of the
key shape refused with its name and never the value (KEY_NOT_KEY_SHAPED: empty, whitespace anywhere, an admin key,
another prefix, another character, too short, too long), nothing stored; an existing entry refused without
--replace before any prompt (KEY_ENTRY_EXISTS) and replaced with it; a cancelled prompt (KEY_ENTRY_CANCELLED); the
key stored through credential-set's custody path (the entry, its read back, the aieh-credential-act/1 receipt);
the output names the entry and reminds the Owner to clear the clipboard, and holds neither the key (searched in
every form by inference_key_search) nor its fingerprint, length or prefix; no store record holds the key; the key
has no command-line option. An in-memory credential provider and a fixture integration store only: nothing here
reads, writes or enumerates the real Credential Manager, and nothing reads a real console.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock
import warnings
from pathlib import Path

import broker_support as S

CATEGORY = 'unit'
IB = S.IB
KS = S._load('aieh_inference_key_search', S.HERE.parent / 'inference_key_search.py')
# Synthetic keys of the provider's API key form, built at run time (never a literal of a real key's shape).
KEY = 'sk-ant-api' + '03-' + 'SyntheticEnteredKey_NOT-A-REAL-CREDENTIAL_' + 'q7' * 20
OTHER = 'sk-ant-api' + '03-' + 'SyntheticReplacementKey_NOT-REAL_' + 'z4' * 20
PROVIDER = 'anthropic'


class FakeConsole:
    """An injected console: whether it is interactive, and what the hidden prompt answers (a value, or an exception
    to raise). It records each prompt it was asked."""

    def __init__(self, answer=KEY, *, interactive=True):
        self.answer, self.is_interactive, self.prompts = answer, interactive, []

    def interactive(self):
        return self.is_interactive

    def read_hidden(self, prompt):
        self.prompts.append(prompt)
        if isinstance(self.answer, BaseException):
            raise self.answer
        return self.answer


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-inference-enter-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.db = self.tmp / 'integration.sqlite'

    def context(self, console, provider):
        def refuse(*args):
            raise AssertionError('credential-enter touched the logs or served')
        return IB.Context(component=lambda: None, provider=lambda: provider,
                          store=lambda: S.STORE.open_store(self.db), logs=refuse, stdin=None, out=io.StringIO(),
                          err=io.StringIO(), wait=refuse, console=console)

    def run_command(self, console, provider, *extra, provider_id=PROVIDER):
        ctx = self.context(console, provider)
        code = IB.main(['credential-enter', '--provider', provider_id, *extra], ctx)
        return code, ctx.out.getvalue(), ctx.err.getvalue()

    def store_text(self) -> str:
        if not self.db.exists():
            return ''
        store = S.STORE.open_store(self.db)
        try:
            return store.canonical_dump().decode('utf-8', 'replace')
        finally:
            store.close()

    def assertNothingDerived(self, text, *keys):
        """TEXT holds no key of KEYS in any form the key search knows, and none of their fingerprints."""
        for key in keys:
            self.assertFalse(KS.Search(key).holds(text))
            self.assertNotIn(IB.contract.fingerprint(key), text)
            self.assertNotIn(KS.fingerprint(key), text)
            self.assertNotIn(key[:16], text)


class TheRules(unittest.TestCase):
    def test_a_key_shaped_value_meets_every_rule(self):
        for value in (KEY, 'sk-ant-api' + 'x' * 30, 'sk-ant-api' + 'A_b-9' * 100 + 'zz'):
            with self.subTest(length=len(value)):
                self.assertIsNone(IB.entered_key_rule(value))

    def test_each_rule_is_named(self):
        cases = {
            'empty': ('', None),
            'whitespace': (KEY + '\n', KEY + '\r\n', ' ' + KEY, KEY[:20] + ' ' + KEY[20:], KEY + '\t',
                           KEY[:20] + ' ' + KEY[20:], '\n'),
            'admin-key': ('sk-ant-admin01-' + 'a' * 60,),
            'prefix': ('sk-ant-oat01-' + 'a' * 60, 'sk-proj-' + 'a' * 60, 'SK-ANT-API03-' + 'a' * 60,
                       'xsk-ant-api03-' + 'a' * 60),
            'characters': (KEY + '=', KEY[:20] + '.' + KEY[20:], KEY + 'é', KEY + '/'),
            'length': ('sk-ant-api' + 'a' * 29, 'sk-ant-api' + 'a' * 503),
        }
        for rule, values in cases.items():
            for value in values:
                with self.subTest(rule=rule, length=None if value is None else len(value)):
                    self.assertEqual(IB.entered_key_rule(value), rule)
        self.assertEqual([name for name, _ in IB.ENTERED_KEY_RULES], list(cases))

    def test_the_bound_is_broad_and_named(self):
        self.assertEqual(IB.ENTERED_KEY_LENGTH, (40, 512))
        self.assertIsNone(IB.entered_key_rule('sk-ant-api' + 'a' * 30))           # 40
        self.assertIsNone(IB.entered_key_rule('sk-ant-api' + 'a' * 502))          # 512


class Command(Fixture):
    def test_a_pasted_key_is_stored_and_nothing_derived_from_it_is_shown(self):
        provider, console = S.MemoryProvider(), FakeConsole()
        code, out, err = self.run_command(console, provider)
        self.assertEqual(code, 0, err)
        self.assertEqual(provider.entries, {IB.ENTRY: (PROVIDER, KEY)})
        self.assertEqual(console.prompts, [IB.KEY_PROMPT])                     # asked once
        report = json.loads(out)
        self.assertEqual((report['format'], report['entry'], report['user'], report['verb'], report['stored'],
                          report['read_back']),
                         ('aieh-inference-credential-enter/1', 'AIEH model provider', PROVIDER, 'provision', True,
                          True))
        self.assertIn('stored in the credential entry "AIEH model provider"', report['message'])
        self.assertEqual(report['reminder'], IB.CLIPBOARD_REMINDER)
        self.assertIn('Clear the clipboard', report['reminder'])
        self.assertEqual(set(report['receipt']), {'operation_key', 'format', 'state'})
        self.assertEqual((report['receipt']['format'], report['receipt']['state']),
                         ('aieh-credential-act/1', 'confirmed'))
        self.assertIn('I7 no-exposure scan: clean', err)
        self.assertNothingDerived(out + err, KEY)
        self.assertNotIn(str(len(KEY)), out)
        self.assertNotIn('fingerprint', out)
        # the store: the custody path's receipt (aieh-credential-act/1, fingerprints only), never the key
        store_text = self.store_text()
        self.assertFalse(KS.Search(KEY).holds(store_text))
        store = S.STORE.open_store(self.db)
        try:
            (attempt,) = store.attempts()
            intent = json.loads(store.get(attempt.operation_key).intent_json)
            self.assertEqual((attempt.operation_key, attempt.state), (report['receipt']['operation_key'],
                                                                      'confirmed'))
            self.assertEqual((intent['format'], intent['verb'], intent['entry'], intent['user'], intent['revoker']),
                             ('aieh-credential-act/1', 'provision', 'AIEH model provider', PROVIDER,
                              'Owner (inference_broker.py credential-set)'))
        finally:
            store.close()

    def test_not_a_console_is_refused_before_any_prompt(self):
        provider, console = S.MemoryProvider(), FakeConsole(interactive=False)
        code, out, err = self.run_command(console, provider)
        self.assertEqual((code, out), (2, ''))
        self.assertIn('KEY_CONSOLE_REQUIRED', err)
        self.assertEqual((console.prompts, provider.entries, self.store_text()), ([], {}, ''))

    def test_every_value_that_is_not_key_shaped_is_refused_naming_the_rule_only(self):
        values = {'empty': '', 'whitespace': KEY + '\n', 'admin-key': 'sk-ant-admin01-' + 'B' * 60,
                  'prefix': 'sk-ant-oat01-' + 'C' * 60, 'characters': KEY + '+', 'length': KEY * 6}
        for rule, value in values.items():
            with self.subTest(rule=rule):
                provider = S.MemoryProvider()
                code, out, err = self.run_command(FakeConsole(value), provider)
                self.assertEqual((code, out), (2, ''))
                self.assertIn('KEY_NOT_KEY_SHAPED', err)
                self.assertIn(f'refused by the rule {rule}', err)
                self.assertIn('paste the dedicated provider key again', err)
                self.assertEqual(provider.entries, {})
                if value:
                    self.assertNotIn(value.strip()[12:40], err)
                self.assertNothingDerived(err, KEY)
        self.assertEqual(self.store_text(), '')

    def test_an_existing_entry_is_refused_before_any_prompt_without_replace(self):
        provider, console = S.MemoryProvider({IB.ENTRY: (PROVIDER, OTHER)}), FakeConsole()
        code, out, err = self.run_command(console, provider)
        self.assertEqual((code, out), (2, ''))
        self.assertIn('KEY_ENTRY_EXISTS', err)
        self.assertIn('--replace', err)
        self.assertEqual((console.prompts, provider.entries), ([], {IB.ENTRY: (PROVIDER, OTHER)}))
        self.assertNothingDerived(err, OTHER)
        self.assertEqual(self.store_text(), '')

    def test_with_replace_an_existing_entry_is_rotated(self):
        provider, console = S.MemoryProvider({IB.ENTRY: (PROVIDER, OTHER)}), FakeConsole()
        code, out, err = self.run_command(console, provider, '--replace')
        self.assertEqual(code, 0, err)
        self.assertEqual(provider.entries, {IB.ENTRY: (PROVIDER, KEY)})
        self.assertEqual(json.loads(out)['verb'], 'rotate')
        self.assertNothingDerived(out + err, KEY, OTHER)
        self.assertFalse(KS.Search(KEY).holds(self.store_text()))
        self.assertFalse(KS.Search(OTHER).holds(self.store_text()))

    def test_replace_without_an_entry_provisions(self):
        provider = S.MemoryProvider()
        code, out, err = self.run_command(FakeConsole(), provider, '--replace')
        self.assertEqual((code, json.loads(out)['verb']), (0, 'provision'), err)

    def test_a_cancelled_prompt_stores_nothing(self):
        for interruption in (KeyboardInterrupt(), EOFError()):
            with self.subTest(type(interruption).__name__):
                provider = S.MemoryProvider()
                code, out, err = self.run_command(FakeConsole(interruption), provider)
                self.assertEqual((code, out), (2, ''))
                self.assertIn('KEY_ENTRY_CANCELLED', err)
                self.assertEqual(provider.entries, {})

    def test_a_bad_provider_id_is_refused_before_any_prompt(self):
        console = FakeConsole()
        code, _, err = self.run_command(console, S.MemoryProvider(), provider_id='Not An Id')
        self.assertEqual(code, 2)
        self.assertIn('PROVIDER_ID_INVALID', err)
        self.assertEqual(console.prompts, [])

    def test_output_that_would_hold_the_key_is_withheld(self):
        class Leaky(S.MemoryProvider):
            def set(self, name, user, secret, comment=''):
                raise RuntimeError(f'backend echoed {secret}')
        code, out, err = self.run_command(FakeConsole(), Leaky())
        self.assertEqual(code, 1)
        self.assertIn('EXPOSURE_FOUND', err)
        self.assertNothingDerived(out + err, KEY)

    def test_the_key_has_no_command_line_option(self):
        for extra in (('--key', KEY), (KEY,)):
            with self.subTest(len(extra)):
                with self.assertRaises(SystemExit):
                    with unittest.mock.patch('sys.stderr', io.StringIO()):
                        IB.main(['credential-enter', '--provider', PROVIDER, *extra],
                                self.context(FakeConsole(), S.MemoryProvider()))

    def test_the_key_is_never_in_the_environment_or_a_file(self):
        provider = S.MemoryProvider()
        before = set(os.environ.items())
        code, _, err = self.run_command(FakeConsole(), provider)
        self.assertEqual(code, 0, err)
        self.assertEqual(set(os.environ.items()), before)
        for path in self.tmp.rglob('*'):
            if path.is_file():
                self.assertFalse(KS.Search(KEY).holds(path.read_bytes()), path.name)


class TheRealConsoleCheck(unittest.TestCase):
    """stdin_is_console on what is not a console (a real console is never needed, or read, here)."""

    def test_a_stream_without_a_descriptor_is_not_a_console(self):
        for stream in (io.StringIO(KEY), io.BytesIO(KEY.encode()), None, object()):
            with self.subTest(type(stream).__name__):
                self.assertFalse(IB.stdin_is_console(stream))

    def test_a_pipe_is_not_a_console(self):
        read, write = os.pipe()
        self.addCleanup(os.close, write)
        with os.fdopen(read, 'rb') as stream:
            self.assertFalse(IB.stdin_is_console(stream))

    def test_a_file_and_the_null_device_are_not_a_console(self):
        tmp = Path(tempfile.mkdtemp(prefix='aieh-inference-enter-'))
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / 'key.txt').write_text(KEY, encoding='ascii')
        for path in (tmp / 'key.txt', os.devnull):
            with self.subTest(str(path)[-8:]):
                with open(path, 'rb') as stream:
                    self.assertFalse(IB.stdin_is_console(stream))

    def test_a_closed_stream_is_not_a_console(self):
        read, write = os.pipe()
        os.close(write)
        stream = os.fdopen(read, 'rb')
        stream.close()
        self.assertFalse(IB.stdin_is_console(stream))

    def test_the_real_console_refuses_on_a_pipe_before_reading(self):
        read, write = os.pipe()
        self.addCleanup(os.close, write)
        with os.fdopen(read, 'rb') as stream:
            console = IB.Console(stream)
            self.assertFalse(console.interactive())
            provider = S.MemoryProvider()
            with unittest.mock.patch('getpass.getpass', side_effect=AssertionError('the prompt was read')):
                with self.assertRaises(IB.InferenceError) as caught:
                    IB.credential_enter(console, provider, lambda: None, PROVIDER, replace=False,
                                        guard=IB.BrokerGuard())
        self.assertEqual(caught.exception.code, 'KEY_CONSOLE_REQUIRED')
        self.assertEqual(provider.entries, {})

    def test_getpass_s_echoing_fallback_is_refused(self):
        import getpass

        def falls_back(prompt):
            warnings.warn('Can not control echo on the terminal.', getpass.GetPassWarning, stacklevel=2)
            return KEY
        with unittest.mock.patch('getpass.getpass', side_effect=falls_back):
            with self.assertRaises(IB.InferenceError) as caught:
                IB.Console(sys.stdin).read_hidden(IB.KEY_PROMPT)
        self.assertEqual(caught.exception.code, 'KEY_CONSOLE_REQUIRED')
        self.assertNotIn(KEY, str(caught.exception))

    def test_the_real_console_reads_through_getpass_with_its_prompt(self):
        seen = []
        with unittest.mock.patch('getpass.getpass', side_effect=lambda prompt: seen.append(prompt) or KEY):
            self.assertEqual(IB.Console(sys.stdin).read_hidden(IB.KEY_PROMPT), KEY)
        self.assertEqual(seen, [IB.KEY_PROMPT])

    def test_the_managed_context_uses_the_real_console_of_standard_input(self):
        source = (S.HERE.parent / 'inference_broker.py').read_text(encoding='utf-8')
        self.assertIn('console=Console(sys.stdin)', source)


if __name__ == '__main__':
    unittest.main()
