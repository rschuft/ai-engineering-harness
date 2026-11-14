"""The Owner's entry of the native Claude Code token (plan leaf E-05.9; decision 0023 section 2.2; OA-31 (e)):
integrations/credentials/native_token_entry.py.

Run from the repository root, under the tools interpreter:

    <tools python> -I -B -m unittest discover -s integrations/credentials/tests -p test_native_token_entry.py -v

Shown: it runs only on an interactive console, refused before any prompt otherwise (NATIVE_CONSOLE_REQUIRED; the
real console check on a pipe, a file and a stream without a descriptor); the token is read once at a hidden prompt
(an injected console reader: never a real console; getpass's echoing fallback refused), never from argv (no option
takes it), the environment, a file, config.yml or the host Claude configuration (sentinels there are never what is
stored); every rule of the shape is refused with its name and never the value (NATIVE_TOKEN_NOT_SHAPED), nothing
stored; an existing entry refused without --replace before any prompt (NATIVE_ENTRY_EXISTS) and replaced with it; a
cancelled prompt (NATIVE_ENTRY_CANCELLED); exactly one named entry written and read back, with an
aieh-credential-act/1 receipt carrying the fingerprint only; the output holds neither the token (in any form the key
search knows) nor its fingerprint. An in-memory credential provider and a fixture integration store only: nothing
here reads, writes or enumerates the real Credential Manager, and nothing reads a real console.
"""
from __future__ import annotations

import importlib.util
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

CATEGORY = 'unit'

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]


def _load(name, path):
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


E = _load('aieh_native_token_entry', HERE.parent / 'native_token_entry.py')
NT = E.native_token
K = E.credentials
STORE = _load('integration_store', REPO / 'integrations' / 'store' / 'integration_store.py')
NS = _load('native_support', REPO / 'integrations' / 'dispatch' / 'tests' / 'native_support.py')
KS = _load('aieh_inference_key_search', REPO / 'integrations' / 'inference' / 'inference_key_search.py')
TOKEN = NS.token('E-05.9 entered token')
OTHER = NS.token('E-05.9 replacement token')
SENTINEL = NS.token('E-05.9 sentinel: never read')


class Memory(K.contract.CredentialProvider):
    """An in-memory credential provider; every call recorded."""
    name = 'memory-fake'

    def __init__(self, entries=None):
        self.entries, self.calls = dict(entries or {}), []

    def get(self, name):
        self.calls.append(('get', name))
        return self.entries.get(name)

    def set(self, name, user, secret, comment=''):
        self.calls.append(('set', name))
        self.entries[name] = (user, secret)

    def delete(self, name):
        self.calls.append(('delete', name))
        return self.entries.pop(name, None) is not None


class FakeConsole:
    def __init__(self, answer=TOKEN, *, interactive=True):
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
        self.tmp = Path(tempfile.mkdtemp(prefix='aieh-native-enter-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.db = self.tmp / 'integration.sqlite'

    def run_command(self, console, provider, *extra):
        ctx = E.Context(provider=lambda: provider, store=lambda: STORE.open_store(self.db), console=console,
                        out=io.StringIO(), err=io.StringIO())
        code = E.main(['enter', *extra], ctx)
        return code, ctx.out.getvalue(), ctx.err.getvalue()

    def store_text(self) -> str:
        if not self.db.exists():
            return ''
        store = STORE.open_store(self.db)
        try:
            return store.canonical_dump().decode('utf-8', 'replace')
        finally:
            store.close()

    def assertNothingDerived(self, text, *tokens):
        for token in tokens:
            self.assertFalse(KS.Search(token, prefix=NT.public_prefix(token)).holds(text))
            self.assertNotIn(NT.fingerprint(token), text)


class Entry(Fixture):
    def test_the_token_is_stored_as_the_one_entry_with_a_fingerprint_receipt(self):
        provider, console = Memory({'AIEH model provider': ('anthropic', SENTINEL)}), FakeConsole()
        code, out, err = self.run_command(console, provider)
        self.assertEqual(code, 0, err)
        self.assertEqual(console.prompts, [E.PROMPT])
        self.assertEqual(provider.entries[NT.ENTRY], (NT.ENTRY_USER, TOKEN))
        self.assertEqual(provider.entries['AIEH model provider'], ('anthropic', SENTINEL))   # untouched
        self.assertEqual([c for c in provider.calls if c[0] != 'get'], [('set', NT.ENTRY)])
        self.assertEqual({name for _, name in provider.calls}, {NT.ENTRY})
        report = json.loads(out)
        self.assertEqual((report['entry'], report['verb'], report['stored'], report['read_back']),
                         (NT.ENTRY, 'provision', True, True))
        self.assertEqual(report['receipt']['state'], 'confirmed')
        self.assertIn('clipboard', report['reminder'])
        self.assertNothingDerived(out + err, TOKEN)
        stored = self.store_text()
        self.assertIn(NT.fingerprint(TOKEN), stored)      # the receipt: the fingerprint only
        self.assertFalse(KS.Search(TOKEN, prefix=NT.public_prefix(TOKEN)).holds(stored))
        self.assertIn(E.FORMAT, out)
        self.assertIn('aieh-credential-act/1', stored)

    def test_an_existing_entry_is_replaced_only_with_replace(self):
        provider = Memory({NT.ENTRY: (NT.ENTRY_USER, TOKEN)})
        console = FakeConsole(OTHER)
        code, out, err = self.run_command(console, provider)
        self.assertEqual((code, console.prompts, out), (2, [], ''))
        self.assertIn('NATIVE_ENTRY_EXISTS', err)
        self.assertEqual(provider.entries[NT.ENTRY][1], TOKEN)
        code, out, err = self.run_command(console, provider, '--replace')
        self.assertEqual(code, 0, err)
        self.assertEqual(provider.entries[NT.ENTRY], (NT.ENTRY_USER, OTHER))
        self.assertEqual(json.loads(out)['verb'], 'rotate')
        stored = self.store_text()
        self.assertIn(NT.fingerprint(TOKEN), stored)    # fingerprint_before
        self.assertIn(NT.fingerprint(OTHER), stored)
        self.assertNothingDerived(out + err, TOKEN, OTHER)

    def test_refused_before_any_prompt_without_a_console(self):
        provider, console = Memory(), FakeConsole(interactive=False)
        code, out, err = self.run_command(console, provider)
        self.assertEqual((code, console.prompts, provider.entries, out), (2, [], {}, ''))
        self.assertIn('NATIVE_CONSOLE_REQUIRED', err)
        self.assertFalse(self.db.exists())

    def test_the_real_console_check_refuses_a_pipe_a_file_and_no_descriptor(self):
        read, write = os.pipe()
        self.addCleanup(os.close, read)
        os.close(write)
        with open(read, 'rb', closefd=False) as pipe:
            self.assertFalse(E.Console(pipe).interactive())
        with open(self.tmp / 'file.txt', 'w+', encoding='utf-8') as file:
            self.assertFalse(E.Console(file).interactive())
        self.assertFalse(E.Console(io.StringIO()).interactive())

    def test_getpass_s_echoing_fallback_is_refused(self):
        import getpass

        def fallback(prompt):
            warnings.warn('can not control echo', getpass.GetPassWarning)
            return 'echoed'
        with unittest.mock.patch.object(getpass, 'getpass', fallback):
            with self.assertRaises(NT.NativeTokenError) as caught:
                E.Console(None).read_hidden('x')
        self.assertEqual(caught.exception.code, 'NATIVE_CONSOLE_REQUIRED')

    def test_each_malformed_value_is_refused_by_its_rule_and_nothing_is_stored(self):
        body = TOKEN[len(NS.PREFIX):]
        values = {'empty': '', 'whitespace': TOKEN + '\n', 'characters': TOKEN + '=', 'prefix': 'x' + TOKEN,
                  'other-credential': 'sk-ant-' + 'api03-' + body, 'length': NS.token('short', 39)}
        self.assertEqual(list(values), [name for name, _ in NT.TOKEN_RULES])
        for rule, value in values.items():
            with self.subTest(rule):
                provider = Memory()
                code, out, err = self.run_command(FakeConsole(value), provider)
                self.assertEqual((code, out, provider.entries), (2, '', {}))
                self.assertIn('NATIVE_TOKEN_NOT_SHAPED', err)
                self.assertIn(f'rule {rule}', err)
                if value:
                    self.assertNotIn(value.strip(), err)
                self.assertNotIn(body, err)
        self.assertFalse(self.db.exists())

    def test_a_cancelled_prompt_stores_nothing(self):
        for interruption in (KeyboardInterrupt(), EOFError()):
            with self.subTest(type(interruption).__name__):
                provider = Memory()
                code, out, err = self.run_command(FakeConsole(interruption), provider)
                self.assertEqual((code, provider.entries), (2, {}))
                self.assertIn('NATIVE_ENTRY_CANCELLED', err)

    def test_a_failed_read_back_is_a_failure_recorded_in_the_receipt(self):
        class Lossy(Memory):
            def set(self, name, user, secret, comment=''):
                super().set(name, user, secret[:-1] + ('A' if secret[-1] != 'A' else 'B'), comment)
        code, out, err = self.run_command(FakeConsole(), Lossy())
        self.assertEqual(code, 1)
        self.assertIn('NATIVE_READ_BACK_FAILED', err)
        self.assertIn('"failed"', self.store_text())
        self.assertNothingDerived(out + err, TOKEN)

    def test_the_token_comes_from_the_prompt_only(self):
        """No option takes the token; sentinels in the environment, config.yml's place and a host Claude
        configuration are never what is stored."""
        with self.assertRaises(SystemExit), unittest.mock.patch('sys.stderr', io.StringIO()):
            E.main(['enter', '--token', TOKEN], E.Context(provider=Memory, store=None, console=FakeConsole(),
                                                          out=io.StringIO(), err=io.StringIO()))
        home = self.tmp / 'home'
        (home / '.claude').mkdir(parents=True)
        (home / '.claude' / '.credentials.json').write_text(json.dumps({'claudeAiOauth': {'accessToken': SENTINEL}}),
                                                           encoding='utf-8')
        provider = Memory()
        names = {'CLAUDE_CODE_OAUTH_TOKEN': SENTINEL, 'ANTHROPIC_API_KEY': SENTINEL, 'HOME': str(home),
                 'USERPROFILE': str(home)}
        with unittest.mock.patch.dict(os.environ, names):
            code, out, err = self.run_command(FakeConsole(), provider)
        self.assertEqual(code, 0, err)
        self.assertEqual(provider.entries[NT.ENTRY][1], TOKEN)
        self.assertNotIn(SENTINEL, self.store_text())

    def test_the_command_has_no_value_option(self):
        source = (HERE.parent / 'native_token_entry.py').read_text(encoding='utf-8')
        self.assertEqual(source.count('add_argument('), 1)
        self.assertIn("add_argument('--replace', action='store_true'", source)


if __name__ == '__main__':
    unittest.main()
