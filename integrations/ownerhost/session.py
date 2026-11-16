"""The Owner UI session credential, as the Integration process checks it (plan leaf U-01.3; Proposed decision 0025,
points 3 to 5).

``cred-owner-ui-session`` is one random secret that the Owner mints himself with the enroll command (enroll.py):
``aieh-oui-`` followed by 52 lower-case base32 characters (32 random bytes). It is not shaped like an Agent Server
key (43 URL-safe characters, no prefix), an inference attempt token (``aieh-inf-``), a provider key (``sk-ant-``,
``sk-proj-``) or a Gitea token (40 hexadecimal digits). The Owner conversation store keeps only its **verifier**, the
sha256 of a fixed domain line and the credential, with the session's public id and validity
(integrations/conversation/conversation_store.py).

The shell sends the credential in the request header ``X-AIEH-Owner-Session`` on every request, never in a cookie.
``check`` decides one request: the presented value, if any, is checked for the shape, its verifier is looked up, and
the session's state and expiry are read. It reads the store and nothing else, and changes nothing. The credential
passes through memory only: it is never stored, logged, echoed or put in a refusal.

Refusals (each changes nothing; HTTP 401):

- ``SESSION_CREDENTIAL_MISSING``: no header;
- ``SESSION_CREDENTIAL_FOREIGN``: more than one header, a value not of this shape, or one matching no enrolled
  verifier;
- ``SESSION_CREDENTIAL_REVOKED``: a session superseded by a later enrollment (checked before the expiry: a
  superseded session is refused as revoked whether or not it has also expired);
- ``SESSION_CREDENTIAL_EXPIRED``: the current session, past its expiry.

Standard library only.
"""
from __future__ import annotations

import hashlib
import re

PREFIX = 'aieh-oui-'
BODY_LENGTH = 52                        # base32 of 32 random bytes, padding removed
SECRET_BYTES = 32
SHAPE = re.compile(r'aieh-oui-[a-z2-7]{52}')
DOMAIN = b'ai-engineering-harness/owner-ui-session/v1\n'
HEADER = 'X-AIEH-Owner-Session'
HEADER_KEY = HEADER.lower().encode('ascii')
DEFAULT_HOURS = 12
MAX_HOURS = 7 * 24

REMEDIES = {
    'SESSION_CREDENTIAL_MISSING': f'sign in to the Owner UI with the credential the enroll command showed; every '
                                  f'request carries it in the {HEADER} header',
    'SESSION_CREDENTIAL_FOREIGN': 'this is not the Owner UI session credential: sign in with the one the enroll '
                                  'command showed (aieh-oui- and 52 lower-case base32 characters)',
    'SESSION_CREDENTIAL_EXPIRED': 'the session has expired: run the enroll command at your console and sign in '
                                  'with the new credential',
    'SESSION_CREDENTIAL_REVOKED': 'a later enrollment superseded this session: sign in with the newest credential',
}
STATUS = {code: 401 for code in REMEDIES}


class SessionRefused(Exception):
    """A request refused with a stable code; nothing was read beyond the session table and nothing changed."""

    def __init__(self, code: str, detail: str):
        if code not in REMEDIES:
            raise ValueError(f'unknown refusal code {code!r}')
        self.code, self.detail, self.remedy, self.status = code, detail, REMEDIES[code], STATUS[code]
        super().__init__(f'{code}: {detail} (remedy: {self.remedy})')

    def body(self) -> dict:
        return {'code': self.code, 'detail': self.detail, 'remedy': self.remedy}


def shaped(value) -> bool:
    """Whether VALUE has the credential's shape (nothing about whether it was ever enrolled)."""
    return isinstance(value, str) and SHAPE.fullmatch(value) is not None


def verifier(credential: str) -> str:
    """The verifier the store keeps for CREDENTIAL: sha256 of the domain line and the credential."""
    if not shaped(credential):
        raise ValueError('not an Owner UI session credential')
    return hashlib.sha256(DOMAIN + credential.encode('ascii')).hexdigest()


def check(store, presented: list, now: str):
    """The session that PRESENTED (the request's header values, as bytes or str) authenticates at NOW
    (YYYY-MM-DDTHH:MM:SSZ), or SessionRefused. STORE answers ``session_by_verifier``."""
    if not presented:
        raise SessionRefused('SESSION_CREDENTIAL_MISSING', f'the request has no {HEADER} header')
    if len(presented) != 1:
        raise SessionRefused('SESSION_CREDENTIAL_FOREIGN', f'the request has {len(presented)} {HEADER} headers')
    value = presented[0]
    if isinstance(value, bytes):
        try:
            value = value.decode('ascii')
        except UnicodeDecodeError:
            value = None
    if not shaped(value):
        raise SessionRefused('SESSION_CREDENTIAL_FOREIGN', f'the {HEADER} value is not of the credential\'s shape')
    session = store.session_by_verifier(verifier(value))
    if session is None:
        raise SessionRefused('SESSION_CREDENTIAL_FOREIGN', 'the credential matches no enrolled session')
    if not session.current:
        raise SessionRefused('SESSION_CREDENTIAL_REVOKED', f'session {session.session_id} was superseded by '
                                                           f'session {session.superseded_by}')
    if now >= session.expires_at:
        raise SessionRefused('SESSION_CREDENTIAL_EXPIRED', f'session {session.session_id} expired at '
                                                           f'{session.expires_at}')
    return session
