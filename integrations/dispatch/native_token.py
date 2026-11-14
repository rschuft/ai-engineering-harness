"""The native Claude Code token's grammar, its entry and the dispatcher's read (plan leaf E-05.9; decision 0023
sections 2 and 6).

For the native execution profile the unmodified Claude Code authenticates with the Owner's own long-lived token
(``claude setup-token``, run by the Owner through the provider's own flow), delivered to a D1 attempt as
``CLAUDE_CODE_OAUTH_TOKEN`` in the create's ``secrets``.

* **The entry** (decision 0023 section 2.2): one entry of the harness's credential provider (F-06.3), name
  ``ENTRY``, user ``ENTRY_USER``. It is a new, separate credential: never the broker's ``AIEH model provider``,
  never ``cred-owner-provider-login``, never the host Claude configuration. Only the Owner-run entry command writes
  it (``integrations/credentials/native_token_entry.py``, the Owner's act OA-31 (e)): this package only reads a
  credential provider, never writes one.
* **The dispatcher's read** (``read``): ``provider.get(ENTRY)`` once, and no other entry. ``dispatch_inputs``
  calls it for a D1 create on the native profile only after the reservation and every other input are admitted.
  The token is held in memory (``NativeToken``): its ``repr`` and ``record()`` carry the fingerprint only.

**The token's shape** (``token_rule``; the determination of E-05.9, with its sources): neither the provider's
documentation nor the pinned CLI states the exact shape of the value ``claude setup-token`` prints. The
documentation calls it "OAuth access token for claude.ai authentication" (code.claude.com/docs/en/env-vars,
``CLAUDE_CODE_OAUTH_TOKEN``) and shows it only as ``your-token`` (docs/en/authentication, "Generate a long-lived
token"); the pinned CLI (claude 2.1.220) prints the token exchange's ``accessToken`` unchecked and reads the
variable as any non-empty string. What both do state is the grammar of the provider's credentials: the CLI strips
the prefix ``^sk-ant-[a-z0-9]+-`` from its OAuth session tokens and redacts ``\\bsk-ant-[A-Za-z0-9_-]{8,}`` as a
token; the documentation shows OAuth access tokens as ``sk-ant-oat01-...`` (routine trigger tokens, environment
keys), session tokens as ``sk-ant-cc-`` and ``sk-ant-si-``, and API keys as ``sk-ant-api03-...``. So the shape
admitted here is that grammar: ``sk-ant-``, a lower-case label of letters and digits, ``-``, then only letters,
digits, ``_`` and ``-``, 40 to 512 characters in all (a broad bound, as the broker's entered-key rule), no
whitespace; the labels of the provider's other credentials are refused (``api...``: an API key, a second
authentication method; ``admin...``; ``sid...``: a claude.ai session key; ``cc`` and ``si``: session tokens). The
label is not narrowed to ``oat01``: no source states it for this token (a residual, E-05.9's report).

Standard library only: importing this module (``dispatch_inputs`` and ``create_secrets`` do, lazily) loads no
credential, inference or store module.
"""
from __future__ import annotations

import hashlib
import re

ENTRY = 'AIEH Claude Code native token'       # the one credential-provider entry (decision 0023 section 2.2)
ENTRY_USER = 'claude-code'
RECORD_FORMAT = 'ai-engineering-harness/dispatch/native-token/v1'
FINGERPRINT_SHAPE = re.compile(r'sha256:[0-9a-f]{16}')

# The shape (module docstring): sk-ant-<label>-<body>, the provider's credential grammar.
PREFIX = re.compile(r'sk-ant-([a-z0-9]+)-')
CHARACTERS = re.compile(r'[A-Za-z0-9_-]+')
TOKEN_LENGTH = (40, 512)
OTHER_LABEL_PREFIXES = ('api', 'admin', 'sid')     # an API key, an admin key, a claude.ai session key
OTHER_LABELS = ('cc', 'si')                        # session tokens (sk-ant-cc-, sk-ant-si-)
# The rules a value must meet, in the order they are checked; a refusal names the first one it fails.
TOKEN_RULES = (
    ('empty', 'the value is empty'),
    ('whitespace', 'the value holds a space, a tab or a line break (it is not stripped)'),
    ('characters', 'the value holds a character other than a letter, a digit, "_" or "-"'),
    ('prefix', 'the value does not begin sk-ant-, a lower-case label of letters and digits, and "-"'),
    ('other-credential', 'the value is another provider credential (an API key sk-ant-api..., an admin key, a '
                         'session key sk-ant-sid..., a session token sk-ant-cc- or sk-ant-si-)'),
    ('length', f'the value is not {TOKEN_LENGTH[0]} to {TOKEN_LENGTH[1]} characters long'),
)
CODES = {
    'NATIVE_CONSOLE_REQUIRED': 'run the entry command in your own console window, at its prompt: standard input must '
                               'be an interactive console (not a pipe, a file or a redirection), read with echo off',
    'NATIVE_ENTRY_EXISTS': f'the entry "{ENTRY}" exists: run the entry command with --replace to replace it',
    'NATIVE_ENTRY_CANCELLED': 'the prompt was cancelled and nothing was stored: run the entry command again',
    'NATIVE_TOKEN_NOT_SHAPED': 'paste exactly the token claude setup-token printed: sk-ant-, a lower-case label, "-", '
                               'then only letters, digits, "_" and "-", 40 to 512 characters, no space or line break',
    'NATIVE_READ_BACK_FAILED': 'the entry did not read back as written: run the entry command again with --replace',
    'NATIVE_TOKEN_MISSING': f'the Owner enters the token first (OA-31 (e)): the entry "{ENTRY}" holds none',
    'NATIVE_TOKEN_UNAVAILABLE': 'the credential provider could not be read: run as the account that holds the entry',
    'NATIVE_ENTRY_USER_MISMATCH': f'the entry is not of user {ENTRY_USER}, the entry command\'s: the Owner enters '
                                  'the token again with the entry command (--replace)',
}


class NativeTokenError(Exception):
    """A refusal (exit 2) or failure (exit 1) with a stable code of CODES; never the token."""

    def __init__(self, code: str, detail: str, *, refusal: bool = True):
        if code not in CODES:
            raise ValueError(f'unknown code {code!r}')
        self.code, self.detail, self.refusal, self.remedy = code, detail, refusal, CODES[code]
        super().__init__(f'{code}: {detail}. Remedy: {self.remedy}.')


def fingerprint(token: str) -> str:
    """What records carry instead of the token (F-06.3's I8 and the broker's form): sha256: and 16 hex digits."""
    return 'sha256:' + hashlib.sha256(token.encode('utf-8')).hexdigest()[:16]


def token_rule(value) -> str | None:
    """The name of the first of TOKEN_RULES that VALUE fails, or None when it has the native token's shape. Nothing
    of the value is returned."""
    if not isinstance(value, str) or not value:
        return 'empty'
    if any(c.isspace() for c in value):
        return 'whitespace'
    if not value.isascii() or not CHARACTERS.fullmatch(value):
        return 'characters'
    match = PREFIX.match(value)
    if match is None or len(value) == match.end():
        return 'prefix'
    label = match.group(1)
    if label in OTHER_LABELS or label.startswith(OTHER_LABEL_PREFIXES):
        return 'other-credential'
    if not TOKEN_LENGTH[0] <= len(value) <= TOKEN_LENGTH[1]:
        return 'length'
    return None


def is_token(value) -> bool:
    return token_rule(value) is None


def public_prefix(token: str) -> str:
    """The token's public part, ``sk-ant-<label>-`` (its shape is checked first)."""
    if not is_token(token):
        raise ValueError('not a native token')
    return PREFIX.match(token).group(0)


def secret_body(token: str) -> str:
    """The token without its public prefix: the part a leak with the prefix stripped would carry."""
    return token[len(public_prefix(token)):]


def rule_detail(rule: str) -> str:
    return f'refused by the rule {rule}: {dict(TOKEN_RULES)[rule]}'


class NativeToken:
    """The native token, read from its entry for one D1 create and held in memory only until the create's transport
    call. ``repr`` and ``record()`` carry its fingerprint; ``token()`` is the only way to it until ``drop()``; it is
    never serialized."""

    __slots__ = ('fingerprint', '_token')

    def __init__(self, token: str):
        if not is_token(token):
            raise ValueError('not a native token')
        self.fingerprint, self._token = fingerprint(token), token

    def __repr__(self):
        return f'NativeToken(fingerprint={self.fingerprint!r}, open={self.open})'

    __str__ = __repr__

    def __reduce__(self):
        raise TypeError('the native token is not serializable')

    @property
    def open(self) -> bool:
        return self._token is not None

    def token(self) -> str:
        if self._token is None:
            raise ValueError('the native token is no longer held')
        return self._token

    def drop(self) -> None:
        """Release the in-memory token (the entry is unchanged)."""
        self._token = None

    def record(self) -> dict:
        """What a record may carry: the entry and the token's fingerprint, never the token."""
        return {'format': RECORD_FORMAT, 'entry': ENTRY, 'tokenFingerprint': self.fingerprint}


def read(provider) -> NativeToken:
    """The dispatcher's read (decision 0023 section 2.2): exactly one ``provider.get(ENTRY)``, and no other entry.
    NATIVE_TOKEN_UNAVAILABLE when the provider fails, NATIVE_TOKEN_MISSING when the entry holds nothing, and
    NATIVE_ENTRY_USER_MISMATCH when its user is not ENTRY_USER (the entry command's: an entry another writer made is
    not the Owner's token), and NATIVE_TOKEN_NOT_SHAPED when it holds a value without the token's shape (named by
    rule, never the value)."""
    if provider is None or not callable(getattr(provider, 'get', None)):
        raise NativeTokenError('NATIVE_TOKEN_UNAVAILABLE', 'no credential provider was given')
    try:
        entry = provider.get(ENTRY)
    except Exception as exc:  # noqa: BLE001 - reported by type, never by message (it may name the entry's content)
        raise NativeTokenError('NATIVE_TOKEN_UNAVAILABLE', f'the credential provider failed ({type(exc).__name__})',
                               refusal=False) from None
    if entry is None:
        raise NativeTokenError('NATIVE_TOKEN_MISSING', f'the entry "{ENTRY}" does not exist')
    user, value = entry if isinstance(entry, tuple) and len(entry) == 2 else (None, None)
    del entry
    if user != ENTRY_USER:
        del value
        raise NativeTokenError('NATIVE_ENTRY_USER_MISMATCH', f'the entry "{ENTRY}" is not of user {ENTRY_USER}')
    rule = token_rule(value)
    if rule is not None:
        del value
        raise NativeTokenError('NATIVE_TOKEN_NOT_SHAPED', f'the entry "{ENTRY}" holds a value {rule_detail(rule)}')
    return NativeToken(value)
