"""The Owner's enrollment of the Owner UI session credential (plan leaf U-01.3; decision 0025, point 3;
the Owner's act OA-32 (a) for I1's run).

``cred-owner-ui-session`` is minted here, for the Owner to run in his own console window:

* It refuses before anything else unless standard input **and** standard output are console handles
  (``ENROLL_NOT_INTERACTIVE``): the broker's own console check, reused (on Windows a console mode, which a pipe, a
  file, the null device or a redirection does not have; not ``isatty`` alone). It refuses plain pipes and
  redirected handles: an ordinary tool shell that runs it by accident obtains nothing and writes nothing.
* What the guard is not: it is no defence against a process of the Owner's account that gives the command a console
  (a console of its own, hidden or not, or a pseudoconsole, ConPTY) and reads what it shows, or that calls
  ``enroll()`` or writes the store directly. No console check can tell the Owner from such a process: that is
  decision 0010 point 1's accepted same-account limit, named in decision 0025's Consequences. Any such enrollment
  supersedes the Owner's session, which then answers ``SESSION_CREDENTIAL_REVOKED`` at his next request, unless a
  same-account writer of the store undoes it first (decision 0010 point 1).
* It generates 32 random bytes (``secrets``), the credential ``aieh-oui-`` and their lower-case base32 (52
  characters), and writes one session row to the Owner conversation store: the session's public id (a random
  UUID), the credential's **verifier** (session.py), the issue time and the expiry (``--hours``, default 12,
  1 to 168). The credential itself is never stored. The new session supersedes the current one, which is refused
  afterwards (``SESSION_CREDENTIAL_REVOKED``): one session is current.
* It shows the credential once, on the console, with the session id and the expiry, for the Owner to paste into
  the Owner UI's sign-in; it prints nothing else derived from it.

  <tools python> -I -B integrations/ownerhost/enroll.py [--hours N]       # task ownerhost:enroll

The store is ``<state>/owner-host/conversation.sqlite`` of the managed data root (decision 0009). Tests call
``enroll`` with a throwaway store and never run the command against the managed root. Exit 0 enrolled, 2 refused
(a stable code).
"""
from __future__ import annotations

import argparse
import base64
import datetime
import importlib.util
import os
import secrets
import sys
import uuid
from pathlib import Path
from typing import Callable

HERE = Path(os.path.realpath(__file__)).parent
REPO = HERE.parents[1]


def _load(name: str, path: Path):
    if (module := sys.modules.get(name)) is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = sys.modules[name] = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except BaseException:
            del sys.modules[name]
            raise
    return module


session = _load('aieh_ownerhost_session', HERE / 'session.py')
conversation = _load('aieh_conversation_store', REPO / 'integrations' / 'conversation' / 'conversation_store.py')

REMEDIES = {
    'ENROLL_NOT_INTERACTIVE': 'run the enroll command yourself, in your own console window, with neither standard '
                              'input nor standard output redirected: the credential is shown once, on the console',
    'ENROLL_HOURS_INVALID': f'give --hours as a whole number from 1 to {session.MAX_HOURS}',
    'ENROLL_STORE_REFUSED': 'the Owner conversation store refused to open; see the detail',
}


class EnrollRefused(Exception):
    def __init__(self, code: str, detail: str):
        self.code, self.detail = code, detail
        super().__init__(f'{code}: {detail} (remedy: {REMEDIES[code]})')


def is_console(stream) -> bool:
    """Whether STREAM is an interactive console: the broker's own check (S-03.3; on Windows a console mode, not
    merely isatty), reused, not copied. Loaded on first use, so that importing this module loads no broker."""
    broker = _load('aieh_inference_broker', REPO / 'integrations' / 'inference' / 'inference_broker.py')
    return broker.stdin_is_console(stream)


def console_guard(stdin, stdout, check: Callable = None) -> None:
    """ENROLL_NOT_INTERACTIVE unless both STDIN and STDOUT are console handles (gate G8)."""
    check = check or is_console
    for name, stream in (('standard input', stdin), ('standard output', stdout)):
        if not check(stream):
            raise EnrollRefused('ENROLL_NOT_INTERACTIVE', f'{name} is not a console')


def mint(entropy: Callable[[int], bytes] = secrets.token_bytes) -> str:
    """A new credential: aieh-oui- and the lower-case base32 of 32 random bytes, padding removed (52 characters)."""
    raw = entropy(session.SECRET_BYTES)
    if not isinstance(raw, bytes) or len(raw) != session.SECRET_BYTES:
        raise ValueError(f'the entropy source must give {session.SECRET_BYTES} bytes')
    credential = session.PREFIX + base64.b32encode(raw).decode('ascii').rstrip('=').lower()
    if not session.shaped(credential):
        raise ValueError('the minted credential does not have the credential shape')
    return credential


def _stamp(moment: datetime.datetime) -> str:
    return moment.astimezone(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def enroll(store, *, hours: int = session.DEFAULT_HOURS, clock: Callable[[], datetime.datetime] = None,
           entropy: Callable[[int], bytes] = secrets.token_bytes,
           new_id: Callable[[], uuid.UUID] = uuid.uuid4) -> tuple[str, object]:
    """Mint a credential and record its session in STORE (a ConversationStore), superseding the current one.
    Returns (credential, session); the credential is returned to the caller only, to be shown once."""
    if type(hours) is not int or not 1 <= hours <= session.MAX_HOURS:
        raise EnrollRefused('ENROLL_HOURS_INVALID', f'--hours {hours!r}')
    issued = (clock or (lambda: datetime.datetime.now(datetime.timezone.utc)))().replace(microsecond=0)
    credential = mint(entropy)
    record = store.enroll_session(session_id=str(new_id()), verifier=session.verifier(credential),
                                  issued_at=_stamp(issued), expires_at=_stamp(issued + datetime.timedelta(hours=hours)))
    return credential, record


def announce(credential: str, record, out) -> None:
    """The one place the credential is shown: on the Owner's console."""
    out.write('Owner UI session credential (shown once; paste it into the Owner UI sign-in, then clear the screen):\n'
              f'\n  {credential}\n\n'
              f'Session {record.session_id}, issued {record.issued_at}, expires {record.expires_at}.\n'
              + (f'It supersedes session {record.supersedes}, which is refused from now on.\n' if record.supersedes
                 else ''))
    out.flush()


def _paths():
    return _load('aieh_paths', REPO / 'integrations' / 'paths' / 'aieh_paths.py')


def main(argv=None, *, stdin=None, stdout=None, stderr=None, config=None, check: Callable = None) -> int:
    """The enroll command. CONFIG is passed to the managed-root resolver (None: the checkout's config.yml, as every
    harness command); CHECK stands in for the console check in tests."""
    stdin, stdout, stderr = stdin or sys.stdin, stdout or sys.stdout, stderr or sys.stderr
    parser = argparse.ArgumentParser(description='Enroll the Owner UI session credential (the Owner, at a console).')
    parser.add_argument('--hours', type=int, default=session.DEFAULT_HOURS,
                        help=f'validity in hours (default {session.DEFAULT_HOURS}, at most {session.MAX_HOURS})')
    args = parser.parse_args(argv)
    try:
        console_guard(stdin, stdout, check)
        if not 1 <= args.hours <= session.MAX_HOURS:
            raise EnrollRefused('ENROLL_HOURS_INVALID', f'--hours {args.hours}')
        paths = _paths()
        directory = paths.ensure('state', paths.resolve(config=config), conversation.COMPONENT)
        try:
            store = conversation.open_store(directory / conversation.DB_NAME)
        except conversation.StoreError as exc:
            raise EnrollRefused('ENROLL_STORE_REFUSED', str(exc)) from None
        try:
            credential, record = enroll(store, hours=args.hours)
        finally:
            store.close()
    except EnrollRefused as exc:
        stderr.write(f'{exc}\n')
        return 2
    announce(credential, record, stdout)
    return 0


if __name__ == '__main__':
    sys.exit(main())
