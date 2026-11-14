"""The Owner's entry of the native Claude Code token (plan leaf E-05.9; decision 0023 section 2.2; the Owner's act
OA-31 (e)).

The Owner runs ``claude setup-token`` on the host through the provider's own flow and pastes the token it prints
here, once, in his own console window. The command writes exactly one entry of the harness's credential provider
(F-06.3, this package): name ``AIEH Claude Code native token``, user ``claude-code`` (``native_token.ENTRY``,
``ENTRY_USER``; integrations/dispatch/native_token.py holds the token's grammar and the dispatcher's read, and that
package only ever reads a provider).

* It refuses before any prompt unless standard input is an interactive console (NATIVE_CONSOLE_REQUIRED; the
  broker's own console check, reused) and, for an existing entry, unless ``--replace`` is given
  (NATIVE_ENTRY_EXISTS).
* It reads the token once at a hidden prompt (getpass: echo off, read from the console itself; getpass's echoing
  fallback is refused), never from argv (it has no option for it), the environment, a file, ``config.yml`` or the
  host Claude configuration.
* It refuses an empty or malformed value naming the rule, never the value (NATIVE_TOKEN_NOT_SHAPED;
  ``native_token.token_rule``); a cancelled prompt stores nothing (NATIVE_ENTRY_CANCELLED).
* It writes the one entry, reads it back (NATIVE_READ_BACK_FAILED) and leaves an ``aieh-credential-act/1`` receipt
  in the integration store (provision, or rotate when an entry existed) with the token's fingerprint only, read
  back (``ActReceipt``). The report names the entry and the receipt and reminds the Owner to clear the clipboard;
  nothing in it is derived from the token, and the I7 scan withholds any output that would hold it.

This leaf never runs it against the real store: its tests use an injected console, an in-memory provider and a
fixture integration store.

  <tools python> -I -B integrations/credentials/native_token_entry.py enter [--replace]

Exit 0 stored, 1 failed, 2 refused (a stable code).
"""
from __future__ import annotations

import argparse
import dataclasses
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Callable

HERE = Path(os.path.realpath(__file__)).parent
REPO = HERE.parents[1]

FORMAT = 'aieh-native-token-enter/1'
SERVICE = 'dispatch-native-token'
ACTOR = 'native_token_entry enter'
REVOKER = 'Owner (native_token_entry.py enter)'
COMMENT = 'AIEH: the native Claude Code token from claude setup-token (decision 0023)'
PROMPT = 'Paste the token claude setup-token printed (it is not shown), then press Enter: '
CLIPBOARD_REMINDER = ('Clear the clipboard now: the token was pasted from it, and it stays there until something '
                      'else is copied.')


def _load(name: str, path: Path):
    """A module of the repository, loaded by path (``python -I`` adds no script directory)."""
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            del sys.modules[name]
            raise
    return module


native_token = _load('aieh_dispatch_native_token', REPO / 'integrations' / 'dispatch' / 'native_token.py')
credentials = _load('aieh_credential_provider', HERE / 'credential_provider.py')
contract = credentials.contract
NativeTokenError = native_token.NativeTokenError


def stdin_is_console(stream) -> bool:
    """Whether STREAM is an interactive console: the broker's own check (S-03.3; on Windows a console mode, not
    merely isatty), reused, not copied. Loaded on first use."""
    broker = _load('aieh_inference_broker', REPO / 'integrations' / 'inference' / 'inference_broker.py')
    return broker.stdin_is_console(stream)


class Console:
    """The Owner's console: interactive() is ``stdin_is_console(STDIN)``; read_hidden(prompt) reads one line with
    echo off through getpass (the console itself on Windows, the terminal elsewhere); getpass's fallback, which would
    read standard input with echo, is refused (NATIVE_CONSOLE_REQUIRED)."""

    def __init__(self, stdin):
        self.stdin = stdin

    def interactive(self) -> bool:
        return stdin_is_console(self.stdin)

    def read_hidden(self, prompt: str) -> str:
        import getpass
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            try:
                return getpass.getpass(prompt)
            except getpass.GetPassWarning:
                raise NativeTokenError('NATIVE_CONSOLE_REQUIRED', 'echo cannot be turned off on this input') from None


def enter(console, provider, store_factory: Callable, *, replace: bool, guard) -> dict:
    """The Owner's token entry (OA-31 (e)): refuse unless CONSOLE is interactive, and refuse an existing entry
    without REPLACE, both before prompting; read the token once at a hidden prompt; refuse a value without the
    token's shape (naming the rule only); write exactly the entry ``native_token.ENTRY`` through PROVIDER (a
    CredentialProvider) under an ``aieh-credential-act/1`` receipt (provision, or rotate when an entry exists;
    fingerprints only) in the store STORE_FACTORY opens, and read both back. GUARD (the platform contract's
    ExposureGuard) holds the token for the I7 scan of the receipt and of the command's output."""
    entry = native_token.ENTRY
    if not console.interactive():
        raise NativeTokenError('NATIVE_CONSOLE_REQUIRED', 'standard input is not an interactive console')
    previous = provider.get(entry)
    exists = previous is not None
    before = native_token.fingerprint(previous[1]) if exists and isinstance(previous[1], str) else None
    previous_user = previous[0] if exists else None
    del previous
    if exists and not replace:
        raise NativeTokenError('NATIVE_ENTRY_EXISTS', f'the entry "{entry}" exists and --replace was not given')
    try:
        token = console.read_hidden(PROMPT)
    except (KeyboardInterrupt, EOFError):
        raise NativeTokenError('NATIVE_ENTRY_CANCELLED', 'the prompt ended before a token was entered') from None
    rule = native_token.token_rule(token)
    if rule is not None:
        del token
        raise NativeTokenError('NATIVE_TOKEN_NOT_SHAPED', native_token.rule_detail(rule) + '; nothing was stored')
    guard.hold(token)
    verb = 'rotate' if exists else 'provision'
    store = store_factory()
    try:
        receipt = credentials.ActReceipt(
            store, verb=verb, service=SERVICE, entry=entry, user=native_token.ENTRY_USER, role=None,
            fingerprint_before=before, provider=credentials.describe(provider)['provider'],
            trigger='owner direction', revoker=REVOKER, actor=ACTOR, guard=guard).begin()
        try:
            receipt.dispatched()
            provider.set(entry, native_token.ENTRY_USER, token, COMMENT)
            held = provider.get(entry)
            if held is None or held[0] != native_token.ENTRY_USER or held[1] != token:
                raise NativeTokenError('NATIVE_READ_BACK_FAILED', 'the entry does not hold what was written',
                                       refusal=False)
            del held
        except BaseException as exc:
            receipt.abort(exc)
            raise
        result = receipt.finish({'fingerprint_after': native_token.fingerprint(token),
                                 'previous_user': previous_user, 'read_back': True})
    finally:
        store.close()
        del token
    return {'format': FORMAT, 'entry': entry, 'user': native_token.ENTRY_USER, 'verb': verb, 'stored': True,
            'read_back': True, 'message': f'The native Claude Code token is stored in the credential entry "{entry}".',
            'reminder': CLIPBOARD_REMINDER,
            'receipt': {k: result[k] for k in ('operation_key', 'format', 'state')}}


@dataclasses.dataclass
class Context:
    """What the command line acts on. managed_context() is the Owner's: the credential provider the harness chooses
    and the managed root's integration store. A test passes its own, whole (never the real store or console)."""
    provider: Callable           # -> a CredentialProvider
    store: Callable              # -> an open integration store (the caller closes it)
    console: object
    out: object
    err: object


def managed_context() -> Context:
    paths = _load('aieh_paths', REPO / 'integrations' / 'paths' / 'aieh_paths.py')
    store_module = _load('integration_store', REPO / 'integrations' / 'store' / 'integration_store.py')
    res = paths.resolve()
    return Context(provider=credentials.select_provider,
                   store=lambda: store_module.open_store(paths.ensure('state', res, 'integration')
                                                         / 'integration.sqlite'),
                   console=Console(sys.stdin), out=sys.stdout, err=sys.stderr)


def main(argv=None, context: Context | None = None) -> int:
    parser = argparse.ArgumentParser(prog='native_token_entry.py', description='The Owner\'s entry of the native '
                                     'Claude Code token (E-05.9). Exit 0 stored, 1 failed, 2 refused.')
    sub = parser.add_subparsers(dest='command', required=True)
    enter_parser = sub.add_parser('enter', help='in your own console window: paste the token claude setup-token '
                                  f'printed once at a hidden prompt; it is stored as the entry "{native_token.ENTRY}"; '
                                  'prints nothing derived from the token')
    enter_parser.add_argument('--replace', action='store_true', help='replace an existing entry (refused without it)')
    args = parser.parse_args(argv)
    guard = contract.ExposureGuard()
    out, err = (context.out, context.err) if context else (sys.stdout, sys.stderr)
    report, message, code = None, '', 0
    try:
        ctx = context or managed_context()
        report = enter(ctx.console, contract.WatchedProvider(ctx.provider(), guard), ctx.store,
                       replace=args.replace, guard=guard)
    except (NativeTokenError, contract.LifecycleError) as exc:
        message, code = f'native-token: {exc}\n', 2 if exc.refusal else 1
    except Exception as exc:  # noqa: BLE001 - reported by type, after the exposure scan
        message, code = f'native-token: FAILED: {type(exc).__name__}: {str(exc)[:300]}\n', 1
    text = '' if report is None else json.dumps(report, indent=2, sort_keys=True) + '\n'
    clean = guard.scan_text('report', text) and guard.scan_text('message', message)
    guard.clear()
    if not clean:
        err.write('native-token: EXPOSURE_FOUND: the output would hold the token and was withheld\n')
        return 1
    err.write(message)
    out.write(text)
    err.write(f'native-token: I7 no-exposure scan: clean ({len(guard.scanned)} outputs scanned)\n')
    return code


if __name__ == '__main__':
    sys.exit(main())
