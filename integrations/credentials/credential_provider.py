"""The harness's credential provider (plan leaf F-06.3; the accepted cross-platform lifecycle design, draft
decision 0011 section 3; decision 0007 point 5 for the receipts).

Where the harness keeps service credentials, by entry name: get, set, delete, exists. The interface is the
lifecycle contract's CredentialProvider (integrations/platform/platform_contract.py), published here as
CredentialProvider; this module holds its implementations, the factory that chooses one, `doctor`, and the
integration-store receipt of a credential act.

- Windows: Credential Manager generic credentials through CredWriteW, CredReadW and CredDeleteW (advapi32),
  standard-library ctypes only: the provider of plan leaves F-06.1 and S-01.2.2, moved here unchanged from
  integrations/platform/platform_windows.py. keyring is kept off the Windows provider: the factory never
  imports keyring on Windows and never instantiates any keyring backend there (WinVaultKeyring included).
- Linux and macOS: KeyringProvider over keyring 25.7.0 (MIT; hash-locked in the tools lock), with the
  backend instantiated explicitly, SecretService.Keyring() or macOS.Keyring(), and its .priority checked.
  keyring's own backend selection is never used: not get_keyring() or anything of keyring.core, not a
  keyringrc, not PYTHON_KEYRING_BACKEND, not the keyring command line, not keyrings.alt or any plug-in
  entry point; KEYRING_PROPERTY_* environment properties (and the macOS backend's KEYCHAIN_PATH) are
  cleared from the instance, and doctor names what it ignored. keyring is imported only on those systems,
  so this module imports under the basic-tier interpreter; the POSIX lifecycle runs under the tools venv.
- The factory (select_provider) fails closed: with no qualified provider it refuses NO_CREDENTIAL_PROVIDER
  with its remedy, and there is never a file or plaintext fallback. A keyring backend is qualified when its
  .priority is a number above zero and it can find an entry by its name alone (one named entry per
  credential, I2). The harness chooses the provider from the running system, never from configuration or
  the environment (I6).

Credential invariants I1-I8 bind every act (platform_contract.py). Every rotate or retire act writes an
integration-store receipt (ActReceipt; fingerprints only, I8) and reads it back: an act without a receipt
read back is a failure (CREDENTIAL_RECEIPT_UNREAD).

  python -I -B integrations/credentials/credential_provider.py doctor

doctor reports the chosen provider and its viability; it reads, writes and lists no entry and prints no
secret. Exit 0 viable, 2 refused (a stable code), 1 when its I7 scan finds anything.
"""
from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import os
import platform as _platform
import secrets
import sys
from pathlib import Path
from typing import Callable

HERE = Path(os.path.realpath(__file__)).parent
REPO = HERE.parents[1]


def _load_contract():
    if (module := sys.modules.get('aieh_platform_contract')) is None:
        spec = importlib.util.spec_from_file_location('aieh_platform_contract',
                                                      REPO / 'integrations' / 'platform' / 'platform_contract.py')
        module = sys.modules['aieh_platform_contract'] = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except BaseException:
            del sys.modules['aieh_platform_contract']
            raise
    return module


contract = _load_contract()
LifecycleError = contract.LifecycleError
CredentialProvider = contract.CredentialProvider  # the contract's interface (decision 0011 section 3)
fingerprint = contract.fingerprint

DOCTOR_FORMAT = 'aieh-credential-doctor/1'
RECEIPT_FORMAT = 'aieh-credential-act/1'
RECEIPT_REMEDY = ('the act ran but its receipt was not read back, so it counts as failed: check the integration '
                  "store, then rerun the act (every credential act resumes) so that it records a receipt")
# What the harness never uses to choose or configure a keyring backend (decision 0011 section 3).
NEVER_USED = ('keyring.get_keyring() and keyring.core', 'a keyringrc file', 'PYTHON_KEYRING_BACKEND',
              'the keyring command line', 'keyrings.alt and keyring plug-in entry points')


# ---------------------------------------------------------------- Windows Credential Manager


class CredentialStore:
    """Generic credentials through CredWriteW / CredReadW / CredDeleteW (advapi32). Values are bytes in
    memory; nothing here prints or logs them. ERROR_NO_SUCH_LOGON_SESSION (the session has no credential
    store loaded, e.g. a network logon) is CREDENTIAL_PROVIDER_LOCKED."""
    GENERIC, PERSIST_LOCAL_MACHINE, ERROR_NOT_FOUND = 1, 2, 1168
    ERROR_NO_SUCH_LOGON_SESSION = 1312

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        class Credential(ctypes.Structure):
            _fields_ = [('Flags', wintypes.DWORD), ('Type', wintypes.DWORD), ('TargetName', wintypes.LPWSTR),
                        ('Comment', wintypes.LPWSTR), ('LastWritten', wintypes.FILETIME),
                        ('CredentialBlobSize', wintypes.DWORD), ('CredentialBlob', ctypes.POINTER(ctypes.c_ubyte)),
                        ('Persist', wintypes.DWORD), ('AttributeCount', wintypes.DWORD),
                        ('Attributes', wintypes.LPVOID), ('TargetAlias', wintypes.LPWSTR),
                        ('UserName', wintypes.LPWSTR)]
        self._ct, self._Credential = ctypes, Credential
        adv = ctypes.WinDLL('advapi32', use_last_error=True)
        adv.CredWriteW.argtypes = (ctypes.POINTER(Credential), wintypes.DWORD)
        adv.CredReadW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.POINTER(ctypes.POINTER(Credential)))
        adv.CredDeleteW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD)
        adv.CredFree.argtypes = (wintypes.LPVOID,)
        self._adv = adv

    def _locked(self, call: str, target: str, code: int) -> None:
        if code == self.ERROR_NO_SUCH_LOGON_SESSION:
            raise LifecycleError('CREDENTIAL_PROVIDER_LOCKED', f'{call}({target!r}) failed ({code}): this session '
                                                               'has no credential store')

    def write(self, target: str, user: str, secret: bytes, comment: str) -> None:
        ct = self._ct
        blob = (ct.c_ubyte * len(secret)).from_buffer_copy(secret)
        cred = self._Credential(Type=self.GENERIC, TargetName=target, Comment=comment,
                                CredentialBlobSize=len(secret), CredentialBlob=ct.cast(blob, ct.POINTER(ct.c_ubyte)),
                                Persist=self.PERSIST_LOCAL_MACHINE, UserName=user)
        ok = self._adv.CredWriteW(ct.byref(cred), 0)
        ct.memset(blob, 0, len(secret))
        if not ok:
            code = ct.get_last_error()
            self._locked('CredWriteW', target, code)
            raise LifecycleError('CREDENTIAL_WRITE_FAILED', f'CredWriteW({target!r}) failed ({code})',
                                 refusal=False)

    def read(self, target: str) -> tuple[str, bytes] | None:
        ct = self._ct
        pointer = ct.POINTER(self._Credential)()
        if not self._adv.CredReadW(target, self.GENERIC, 0, ct.byref(pointer)):
            if (code := ct.get_last_error()) == self.ERROR_NOT_FOUND:
                return None
            self._locked('CredReadW', target, code)
            raise LifecycleError('CREDENTIAL_READ_FAILED', f'CredReadW({target!r}) failed ({code})', refusal=False)
        try:
            cred = pointer.contents
            return cred.UserName or '', ct.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
        finally:
            self._adv.CredFree(pointer)

    def delete(self, target: str) -> bool:
        if self._adv.CredDeleteW(target, self.GENERIC, 0):
            return True
        if (code := self._ct.get_last_error()) == self.ERROR_NOT_FOUND:
            return False
        self._locked('CredDeleteW', target, code)
        raise LifecycleError('CREDENTIAL_DELETE_FAILED', f'CredDeleteW({target!r}) failed ({code})', refusal=False)


class WindowsCredentialProvider(CredentialProvider):
    """Windows Credential Manager generic credentials (CredentialStore); the secret is stored as UTF-16LE, as
    the Credential Manager UI shows it."""
    name = 'windows-credential-manager'
    mechanism = ('generic credentials through CredWriteW, CredReadW and CredDeleteW (advapi32), persisted per '
                 'local machine for the user')

    def __init__(self, store=None):
        self.store = store or CredentialStore()

    def get(self, name):
        entry = self.store.read(name)
        return None if entry is None else (entry[0], entry[1].decode('utf-16-le'))

    def set(self, name, user, secret, comment=''):
        self.store.write(name, user, secret.encode('utf-16-le'), comment)

    def delete(self, name):
        return self.store.delete(name)

    def describe(self) -> dict:
        return {'provider': self.name, 'mechanism': self.mechanism,
                'viability': 'advapi32 and its Cred* functions are loaded (no entry is read to check it)'}


# ---------------------------------------------------------------- keyring (Linux, macOS)

# The backend each POSIX system uses: keyring's own class, instantiated explicitly by the harness.
KEYRING_BACKENDS = {
    'Linux': {'provider': 'keyring-secret-service', 'module': 'keyring.backends.SecretService', 'class': 'Keyring',
              'mechanism': 'keyring 25.7.0 SecretService.Keyring(), instantiated explicitly: the Secret Service '
                           'of the user session over D-Bus'},
    'Darwin': {'provider': 'keyring-macos-keychain', 'module': 'keyring.backends.macOS', 'class': 'Keyring',
               'mechanism': "keyring 25.7.0 macOS.Keyring(), instantiated explicitly: the user's login Keychain "
                            '(Security framework generic passwords)'},
}
# Class attributes a keyring backend reads from the environment at import: cleared on the instance too.
ENVIRONMENT_CLASS_ATTRIBUTES = ('keychain',)  # macOS.Keyring.keychain = os.environ.get('KEYCHAIN_PATH')
_LOCKED_ERRORS = ('KeyringLocked', 'InitError')  # keyring.errors: the store is locked or unavailable
_CALL_CODES = {'get_credential': 'CREDENTIAL_READ_FAILED', 'set_password': 'CREDENTIAL_WRITE_FAILED',
               'delete_password': 'CREDENTIAL_DELETE_FAILED'}


class KeyringProvider(CredentialProvider):
    """A keyring backend instance the harness chose and qualified (qualify_keyring). One entry per name: the
    keyring service is the entry name, its user name the credential's user, its password the secret. keyring
    has no comment field, so a comment is not stored. A keyring error is reported by its type only (no
    message, which could quote what the backend saw): KeyringLocked and InitError are
    CREDENTIAL_PROVIDER_LOCKED; any other is the call's failure code."""

    def __init__(self, backend, *, name: str, mechanism: str, priority: float, ignored: tuple = ()):
        self.backend, self.name, self.mechanism = backend, name, mechanism
        self.priority, self.ignored = priority, tuple(ignored)

    def _call(self, call: str, entry: str, *args):
        try:
            return getattr(self.backend, call)(*args)
        except Exception as exc:  # noqa: BLE001 - every backend error becomes a stable code
            kinds = {cls.__name__ for cls in type(exc).__mro__}
            if kinds & set(_LOCKED_ERRORS):
                raise LifecycleError('CREDENTIAL_PROVIDER_LOCKED', f'{call}({entry!r}) failed '
                                                                   f'({type(exc).__name__})') from None
            raise LifecycleError(_CALL_CODES[call], f'{call}({entry!r}) failed ({type(exc).__name__})',
                                 refusal=False) from None

    def _user(self, name: str) -> str | None:
        """The user of the entry, or None; its secret is not kept."""
        credential = self._call('get_credential', name, name, None)
        user = None if credential is None else (credential.username or '')
        del credential
        return user

    def get(self, name):
        credential = self._call('get_credential', name, name, None)
        if credential is None:
            return None
        return credential.username or '', credential.password

    def set(self, name, user, secret, comment=''):
        """Create or replace the entry. The new secret is stored first (I3); an entry of the same name under
        another user is deleted after, so one entry per name remains (I2)."""
        previous = self._user(name)
        self._call('set_password', name, name, user, secret)
        if previous is not None and previous != user:
            self._call('delete_password', name, name, previous)

    def delete(self, name):
        previous = self._user(name)
        if previous is None:
            return False
        self._call('delete_password', name, name, previous)
        return True

    def describe(self) -> dict:
        return {'provider': self.name, 'mechanism': self.mechanism, 'priority': self.priority,
                'backend': f'{type(self.backend).__module__}.{type(self.backend).__name__}',
                'ignored_environment_configuration': list(self.ignored)}


def environment_properties() -> list[str]:
    """The instance properties keyring's KeyringBackend.__init__ sets from KEYRING_PROPERTY_* environment
    variables (keyring 25.7.0, set_properties_from_env), named as it names them, so that the harness can clear
    them: the environment never configures the harness's backend."""
    return sorted({key.partition('KEYRING_PROPERTY_')[2].lower() for key in os.environ
                   if 'KEYRING_PROPERTY_' in key} - {''})


def _no_provider(detail: str) -> LifecycleError:
    return LifecycleError('NO_CREDENTIAL_PROVIDER', detail)


def qualify_keyring(system: str, *, import_module: Callable = importlib.import_module) -> KeyringProvider:
    """The system's keyring backend, instantiated explicitly and qualified, or NO_CREDENTIAL_PROVIDER: keyring
    not importable, a priority that raises or is not a number above zero, or a backend that cannot find an
    entry by its name alone (keyring's default get_credential needs the user name)."""
    spec = KEYRING_BACKENDS[system]
    try:
        module = import_module(spec['module'])
        base = import_module('keyring.backend').KeyringBackend
    except ImportError as exc:
        raise _no_provider(f'keyring is not importable here ({exc.name or "keyring"}): the {system} credential '
                           'provider runs under the tools venv (task tools:install)') from None
    backend_class = getattr(module, spec['class'])
    label = f'{spec["module"]}.{spec["class"]}'
    backend = backend_class()
    ignored = []
    for name in environment_properties():  # set from KEYRING_PROPERTY_* by KeyringBackend.__init__
        if name in vars(backend):
            delattr(backend, name)
            ignored.append(f'KEYRING_PROPERTY_{name.upper()}')
    for attribute in ENVIRONMENT_CLASS_ATTRIBUTES:
        if getattr(backend_class, attribute, None) is not None:
            setattr(backend, attribute, None)
            ignored.append(f'{label}.{attribute} (from the environment)')
    try:
        priority = backend.priority
    except Exception as exc:  # noqa: BLE001 - keyring signals a backend that is not viable by raising
        raise _no_provider(f'{label} is not viable here: its priority raised {type(exc).__name__}: '
                           f'{str(exc)[:200]}') from None
    if isinstance(priority, bool) or not isinstance(priority, (int, float)) or not priority > 0:
        raise _no_provider(f'{label} is not viable here: its priority is {priority!r}, not a number above zero')
    if getattr(backend_class, 'get_credential', None) is getattr(base, 'get_credential', None):
        raise _no_provider(f'{label} cannot find an entry by its name alone (keyring\'s default get_credential '
                           'needs the user name), so one named entry per credential (I2) could not be read back')
    return KeyringProvider(backend, name=spec['provider'], mechanism=spec['mechanism'], priority=priority,
                           ignored=tuple(ignored))


# ---------------------------------------------------------------- the factory


def select_provider(system: str | None = None, *, import_module: Callable = importlib.import_module,
                    windows_store: Callable | None = None) -> CredentialProvider:
    """The harness's credential provider for this system (I6: chosen from the running system, never from
    configuration or the environment), or NO_CREDENTIAL_PROVIDER (I5). Windows: Credential Manager; keyring
    is not imported. Linux: keyring's SecretService.Keyring(); macOS: keyring's macOS.Keyring()."""
    system = system or _platform.system()
    if system == 'Windows':
        try:
            store = windows_store() if windows_store is not None else CredentialStore()
        except (OSError, AttributeError) as exc:
            raise _no_provider(f'Credential Manager (advapi32) is not loadable here: {type(exc).__name__}') from None
        return WindowsCredentialProvider(store)
    if system in KEYRING_BACKENDS:
        return qualify_keyring(system, import_module=import_module)
    raise _no_provider(f'no credential provider for system {system!r}: Windows (Credential Manager), Linux (the '
                       'Secret Service) and macOS (the Keychain) only')


def describe(provider) -> dict:
    """What a provider is, for reports: its name and mechanism (a WatchedProvider shows what it wraps)."""
    inner = getattr(provider, 'provider', provider)
    if hasattr(inner, 'describe'):
        return inner.describe()
    return {'provider': getattr(inner, 'name', type(inner).__name__)}


def doctor(system: str | None = None, **factory) -> dict:
    """The chosen provider and its viability, without reading, writing or listing any entry."""
    system = system or _platform.system()
    report = {'format': DOCTOR_FORMAT, 'system': system,
              'chosen_by': 'the harness, from the running system (I6); never configuration or the environment',
              'never_used': list(NEVER_USED), 'entries_touched': 0}
    try:
        provider = select_provider(system, **factory)
    except LifecycleError as exc:
        report.update(provider=None, viable=False,
                      refusal={'code': exc.code, 'detail': exc.detail, 'remedy': exc.remedy})
    else:
        report.update(describe(provider), viable=True, refusal=None)
    report['keyring_imported'] = 'keyring' in sys.modules
    return report


# ---------------------------------------------------------------- receipts


class ActReceipt:
    """The integration-store receipt of one credential act (decision 0007 point 5: fingerprint, role, trigger,
    revoker, affected attempts), written through the store's own receipts: reserved before anything changes,
    dispatched just before the upstream change, then confirmed with the outcome (failed when the harness
    observed it did not apply, unknown when the outcome is uncertain), and read back. Fingerprints only (I8);
    the guard, when given, scans what the receipt holds (I7). store is an open integration store
    (integrations/store/integration_store.py): reserve, transition, get, events."""

    def __init__(self, store, *, verb: str, service: str, entry: str, user: str, role: str | None,
                 fingerprint_before: str | None, provider: str, trigger: str, revoker: str, actor: str,
                 affected_attempts=(), guard=None, stamp: str | None = None):
        if verb not in contract.CREDENTIAL_VERBS:
            raise ValueError(f'{verb!r} is not a credential verb')
        self.store, self.actor, self.guard = store, actor, guard
        stamp = stamp or contract.now()
        subject = role or user
        self.key = f'credential/{service}/{verb}/{subject}/{stamp}-{secrets.token_hex(4)}'
        self.intent = {'format': RECEIPT_FORMAT, 'verb': verb, 'service': service, 'entry': entry, 'user': user,
                       'role': role, 'fingerprint_before': fingerprint_before, 'provider': provider,
                       'trigger': trigger, 'revoker': revoker, 'affected_attempts': list(affected_attempts),
                       'started_at': stamp}
        self.state = None

    def begin(self) -> 'ActReceipt':
        """Reserve the receipt before anything changes: without it the act does not start (I5)."""
        self._scan('receipt intent', json.dumps(self.intent, sort_keys=True))
        self.store.reserve(self.key, self.intent, actor=self.actor)
        self.state = 'reserved'
        return self

    def dispatched(self, reason: str = 'the upstream change starts') -> None:
        self.store.transition(self.key, 'dispatched', actor=self.actor, reason=reason, expected_from='reserved')
        self.state = 'dispatched'

    def abort(self, exc: BaseException) -> None:
        """Record why the act stopped: failed when nothing was sent or the harness refused on what it saw,
        unknown when the outcome is uncertain. A store error here does not hide the act's own error."""
        if self.state not in ('reserved', 'dispatched'):
            return
        code = getattr(exc, 'code', type(exc).__name__)
        to_state = 'failed' if self.state == 'reserved' or isinstance(exc, LifecycleError) else 'unknown'
        try:
            self.store.transition(self.key, to_state, actor=self.actor, reason='the act stopped',
                                  detail={'code': code}, expected_from=self.state)
            self.state = to_state
        except Exception:  # noqa: BLE001 - the act's own error is what the caller sees
            pass

    def finish(self, detail: dict) -> dict:
        """Confirm with the outcome, then read the receipt back: CREDENTIAL_RECEIPT_UNREAD when what the store
        holds is not what was written (an act without a receipt read back is a failure)."""
        if self.state == 'reserved':
            self.dispatched('nothing upstream needed changing (a resumed or empty act)')
        self._scan('receipt detail', json.dumps(detail, sort_keys=True))
        self.store.transition(self.key, 'confirmed', actor=self.actor, reason='the act completed', detail=detail,
                              expected_from='dispatched')
        self.state = 'confirmed'
        return self.read_back(detail)

    def read_back(self, detail: dict) -> dict:
        try:
            record = self.store.get(self.key)
            events = self.store.events(self.key)
            held = (record is not None and record.state == 'confirmed'
                    and json.loads(record.intent_json) == json.loads(json.dumps(self.intent))
                    and bool(events) and events[-1].to_state == 'confirmed'
                    and json.loads(events[-1].detail_json or 'null') == json.loads(json.dumps(detail)))
        except Exception as exc:  # noqa: BLE001 - an unreadable receipt is the failure itself
            raise LifecycleError('CREDENTIAL_RECEIPT_UNREAD', f'{self.key}: the receipt could not be read back '
                                                              f'({type(exc).__name__})', refusal=False,
                                 remedy=RECEIPT_REMEDY) from None
        if not held:
            raise LifecycleError('CREDENTIAL_RECEIPT_UNREAD', f'{self.key}: the store does not hold the receipt '
                                                              'as written', refusal=False, remedy=RECEIPT_REMEDY)
        self._scan('receipt read back', record.intent_json + ''.join(e.detail_json or '' for e in events))
        return {'operation_key': self.key, 'format': RECEIPT_FORMAT, 'state': record.state,
                'events': [event.to_state for event in events], 'read_back': True}

    def _scan(self, name: str, text: str) -> None:
        if self.guard is not None and not self.guard.scan_text(name, text):
            raise LifecycleError('EXPOSURE_FOUND', f'the {name} would hold a secret the act holds', refusal=False)


# ---------------------------------------------------------------- command line


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='credential_provider.py', description="The harness's credential provider "
                                     '(F-06.3). Exit 0 viable, 1 failed, 2 refused.')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('doctor', help='report the chosen provider and its viability; reads no entry, prints no secret')
    parser.parse_args(argv)
    out = sys.stdout
    if hasattr(out, 'reconfigure'):
        out.reconfigure(encoding='utf-8')
    report = doctor()
    text = json.dumps(report, indent=2) + '\n'
    guard = contract.ExposureGuard()
    guard.scan_text('report', text)
    scan = guard.report()
    if scan['found_in']:
        sys.stderr.write('credential-provider: ' + str(LifecycleError('EXPOSURE_FOUND', 'the doctor report holds '
                                                                      'something token-shaped', refusal=False)) + '\n')
        return 1
    out.write(text)
    sys.stderr.write(f'credential-provider: I7 no-exposure scan: clean ({scan["secrets_held"]} secrets held; '
                     f'{scan["scanned"]} outputs scanned)\n')
    return 0 if report['viable'] else 2


if __name__ == '__main__':
    sys.exit(main())
