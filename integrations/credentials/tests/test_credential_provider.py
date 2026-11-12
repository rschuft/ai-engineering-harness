"""Tests of the harness's credential provider (plan leaf F-06.3; draft decision 0011 section 3), offline.

- The provider contract suite runs the same checks over three providers: a fake, the Windows provider
  (Credential Manager's real ctypes code over an in-memory advapi32 stand-in, so the real Credential Manager
  is never called; Windows only) and KeyringProvider over an in-process keyring backend.
- The factory: Credential Manager on Windows without importing keyring; SecretService.Keyring() and
  macOS.Keyring() instantiated explicitly and qualified by their priority and by a lookup by name alone;
  NO_CREDENTIAL_PROVIDER for every unqualified case; keyring's own selection and configuration (get_keyring,
  a keyringrc, PYTHON_KEYRING_BACKEND, KEYRING_PROPERTY_*, the command line, keyrings.alt and plug-ins)
  shown ignored.
- doctor: the chosen provider and its viability, no entry touched, no secret.

keyring 25.7.0 is imported from the tools set (task tools:install): these tests need it and fail without it.
"""
from __future__ import annotations

import ast
import contextlib
import ctypes
import importlib
import importlib.util
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import keyring.backend
import keyring.core
import keyring.errors
import keyring.util.platform_
from keyring.credentials import SimpleCredential

CATEGORY = 'unit'

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / 'credential_provider.py'
WINDOWS = sys.platform == 'win32'
windows_only = unittest.skipUnless(WINDOWS, 'the Windows provider loads advapi32')


def _load(name, path):
    if (module := sys.modules.get(name)) is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = sys.modules[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


K = _load('aieh_credential_provider', SOURCE)
C = K.contract
NAME, OTHER = 'AIEH synthetic entry', 'AIEH synthetic other entry'
SECRET = 'synthetic-sécret-☃-value'


# ---------------------------------------------------------------- the three providers


class MemoryProvider(C.CredentialProvider):
    """The fake: one dict entry per name, under the Windows credential field limits as the Windows provider
    checks them (CREDENTIAL_FIELD_LIMIT, nothing written)."""
    name = 'memory-fake'

    def __init__(self):
        self.entries = {}

    def get(self, name):
        return self.entries.get(name)

    def set(self, name, user, secret, comment=''):
        K.check_credential_fields(name, user, comment, K.secret_blob_size(secret))
        self.entries[name] = (user, secret)

    def delete(self, name):
        return self.entries.pop(name, None) is not None


class MemoryAdvapi:
    """advapi32's CredWriteW, CredReadW, CredDeleteW and CredFree over a dict, through the real ctypes
    structures and pointers of CredentialStore; error, when given, fails every call with that last error."""

    def __init__(self, credential_type, error=None):
        self.Credential, self.error = credential_type, error
        self.entries, self.freed, self._alive, self.writes = {}, 0, [], 0

    def _fail(self, code):
        ctypes.set_last_error(code)
        return 0

    def CredWriteW(self, reference, flags):
        self.writes += 1
        if self.error:
            return self._fail(self.error)
        cred = reference._obj
        blob = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
        self.entries[cred.TargetName] = (cred.UserName, blob, cred.Comment, cred.Type, cred.Persist)
        return 1

    def CredReadW(self, target, kind, flags, reference):
        if self.error:
            return self._fail(self.error)
        if target not in self.entries:
            return self._fail(1168)
        user, blob, comment, _kind, _persist = self.entries[target]
        buffer = (ctypes.c_ubyte * max(len(blob), 1)).from_buffer_copy(blob or b'\0')
        cred = self.Credential(TargetName=target, UserName=user, Comment=comment, CredentialBlobSize=len(blob),
                               CredentialBlob=ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
        self._alive.append((buffer, cred))
        reference._obj.contents = cred
        return 1

    def CredDeleteW(self, target, kind, flags):
        if self.error:
            return self._fail(self.error)
        if self.entries.pop(target, None) is None:
            return self._fail(1168)
        return 1

    def CredFree(self, pointer):
        self.freed += 1


def windows_store(error=None):
    store = K.CredentialStore()  # loads advapi32 and sets argtypes; no Cred* function is called
    store._adv = MemoryAdvapi(store._Credential, error)
    return store


class MemoryKeyring(keyring.backend.KeyringBackend):
    """An in-process keyring backend: (service, user name) -> password, with keyring's lookup by service
    alone; locked, when set, raises keyring's KeyringLocked."""
    priority = 1
    locked = False

    def __init__(self):
        super().__init__()
        self.entries = {}

    def _check(self):
        if type(self).locked:
            raise keyring.errors.KeyringLocked('the collection is locked')

    def get_password(self, service, username):
        self._check()
        return self.entries.get((service, username))

    def set_password(self, service, username, password):
        self._check()
        self.entries[(service, username)] = password

    def delete_password(self, service, username):
        self._check()
        if self.entries.pop((service, username), None) is None:
            raise keyring.errors.PasswordDeleteError('no such password')

    def get_credential(self, service, username):
        self._check()
        for (entry_service, entry_user), password in self.entries.items():
            if entry_service == service and username in (None, entry_user):
                return SimpleCredential(entry_user, password)
        return None


def backend_module(backend_class):
    """An import hook that gives backend_class in the slot of every keyring backend module the factory names,
    and the real module for anything else; it records what was imported."""
    imported = []
    slots = {spec['module'] for spec in K.KEYRING_BACKENDS.values()}

    def import_module(name):
        imported.append(name)
        if name in slots:
            return SimpleNamespace(Keyring=backend_class)
        return importlib.import_module(name)
    import_module.imported = imported
    return import_module


def keyring_provider():
    return K.qualify_keyring('Linux', import_module=backend_module(MemoryKeyring))


class ProviderContract:
    """The provider contract (draft decision 0011 section 3): get, set, delete, exists; one named entry per
    credential (I2); the secret round-trips as a str."""
    category = 'contract'

    def make(self):
        raise NotImplementedError

    def entries_named(self, provider, name) -> int:
        raise NotImplementedError

    def test_is_the_contract_interface(self):
        self.assertIsInstance(self.make(), C.CredentialProvider)
        self.assertIs(K.CredentialProvider, C.CredentialProvider)

    def test_an_absent_entry(self):
        provider = self.make()
        self.assertIsNone(provider.get(NAME))
        self.assertFalse(provider.exists(NAME))
        self.assertFalse(provider.delete(NAME))

    def test_set_then_get_round_trips_the_user_and_the_secret(self):
        provider = self.make()
        provider.set(NAME, 'aieh-synthetic-user', SECRET, 'a synthetic comment')
        self.assertEqual(provider.get(NAME), ('aieh-synthetic-user', SECRET))
        self.assertTrue(provider.exists(NAME))

    def test_replacing_keeps_one_entry_per_name(self):
        provider = self.make()
        provider.set(NAME, 'aieh-synthetic-user', 'first-synthetic-value')
        provider.set(NAME, 'aieh-synthetic-user', 'second-synthetic-value')
        self.assertEqual(provider.get(NAME), ('aieh-synthetic-user', 'second-synthetic-value'))
        provider.set(NAME, 'aieh-other-user', 'third-synthetic-value')
        self.assertEqual(provider.get(NAME), ('aieh-other-user', 'third-synthetic-value'))
        self.assertEqual(self.entries_named(provider, NAME), 1)

    def test_names_are_independent_and_delete_removes_one(self):
        provider = self.make()
        provider.set(NAME, 'aieh-synthetic-user', 'one-synthetic-value')
        provider.set(OTHER, 'aieh-synthetic-user', 'two-synthetic-value')
        self.assertTrue(provider.delete(NAME))
        self.assertIsNone(provider.get(NAME))
        self.assertFalse(provider.delete(NAME))
        self.assertEqual(provider.get(OTHER), ('aieh-synthetic-user', 'two-synthetic-value'))

    def test_a_watched_provider_holds_what_it_reads_and_writes(self):
        guard = C.ExposureGuard()
        provider = C.WatchedProvider(self.make(), guard)
        provider.set(NAME, 'aieh-synthetic-user', SECRET)
        self.assertEqual(provider.get(NAME)[1], SECRET)
        self.assertFalse(guard.scan_text('report', f'... {SECRET} ...'))
        self.assertTrue(guard.scan_text('report', 'fingerprint ' + K.fingerprint(SECRET)))


class WindowsFieldLimits:
    """The Windows credential field limits (CREDENTIAL_LIMITS), enforced before anything is written by the Windows
    provider and by the fake alike: each field at its limit is written, one past it is refused with
    CREDENTIAL_FIELD_LIMIT and nothing is written. Strings count UTF-16 code units, the blob bytes."""
    category = 'contract'
    LIMITS = K.CREDENTIAL_LIMITS
    FITS = {'name': NAME, 'user': 'aieh-synthetic-user', 'secret': 'synthetic-value', 'comment': ''}
    AT_LIMIT = {'TargetName': {'name': 'T' * LIMITS['TargetName'][0]},
                'UserName': {'user': 'u' * LIMITS['UserName'][0]},
                'Comment': {'comment': '☃' * LIMITS['Comment'][0]},  # characters, not UTF-8 bytes
                'CredentialBlob': {'secret': 's' * (LIMITS['CredentialBlob'][0] // 2)}}  # UTF-16LE: 2 bytes each

    def attempts(self, provider) -> int:
        """How many writes reached the store under the provider."""
        raise NotImplementedError

    def test_each_field_at_its_limit_is_written_and_one_past_it_refused_unwritten(self):
        for field, at_limit in self.AT_LIMIT.items():
            with self.subTest(field=field):
                provider = self.make()
                entry = {**self.FITS, **at_limit}
                provider.set(entry['name'], entry['user'], entry['secret'], entry['comment'])
                self.assertEqual(provider.get(entry['name']), (entry['user'], entry['secret']))
                provider = self.make()
                attempts = self.attempts(provider)
                over = {**self.FITS, **{k: v + v[-1] for k, v in at_limit.items()}}
                with self.assertRaises(C.LifecycleError) as caught:
                    provider.set(over['name'], over['user'], over['secret'], over['comment'])
                self.assertEqual((caught.exception.code, caught.exception.refusal), ('CREDENTIAL_FIELD_LIMIT', True))
                self.assertIn(f'{field} is ', caught.exception.detail)
                self.assertIn(self.LIMITS[field][2], caught.exception.detail)
                self.assertIn('nothing was written', caught.exception.detail)
                self.assertNotIn(over['secret'], str(caught.exception))
                self.assertEqual(self.attempts(provider), attempts)
                self.assertIsNone(provider.get(over['name']))

    def test_the_comment_that_failed_with_1734_is_refused_before_the_write(self):
        provider = self.make()
        with self.assertRaises(C.LifecycleError) as caught:
            provider.set(NAME, 'aieh-synthetic-user', 'synthetic-value', 'c' * 271)
        self.assertEqual(caught.exception.code, 'CREDENTIAL_FIELD_LIMIT')
        self.assertIn('Comment is 271 characters, over CRED_MAX_STRING_LENGTH (256)', caught.exception.detail)
        self.assertEqual(self.attempts(provider), 0)


class TestCredentialLimits(unittest.TestCase):
    """The limits themselves and the pure check, which reads and writes no entry."""

    def test_the_limits_and_their_wincred_sources(self):
        self.assertEqual(K.CREDENTIAL_LIMITS, {
            'TargetName': (32767, 'characters', 'CRED_MAX_GENERIC_TARGET_NAME_LENGTH (32767)'),
            'UserName': (513, 'characters', 'CRED_MAX_USERNAME_LENGTH (256+1+256)'),
            'Comment': (256, 'characters', 'CRED_MAX_STRING_LENGTH (256)'),
            'CredentialBlob': (2560, 'bytes', 'CRED_MAX_CREDENTIAL_BLOB_SIZE (5*512)')})
        self.assertEqual((256 + 1 + 256, 5 * 512), (513, 2560))

    def test_the_check_measures_utf16_code_units_and_blob_bytes(self):
        self.assertEqual(K.secret_blob_size('synthetic'), 18)
        self.assertEqual(K.secret_blob_size('\U0001F512'), 4)  # outside the BMP: a surrogate pair
        self.assertEqual(K.secret_blob_size(40), 80)  # a Gitea token's bound
        self.assertEqual(K.credential_field_problems(NAME, 'u', '\U0001F512' * 128, 80), [])
        self.assertEqual(K.credential_field_problems(NAME, 'u', '\U0001F512' * 128 + 'x', 80),
                         ['Comment is 257 characters, over CRED_MAX_STRING_LENGTH (256)'])
        self.assertEqual(K.credential_field_problems(NAME, 'u', '', 2561),
                         ['CredentialBlob is 2561 bytes, over CRED_MAX_CREDENTIAL_BLOB_SIZE (5*512)'])
        self.assertEqual(len(K.credential_field_problems('T' * 32768, 'u' * 514, 'c' * 257, 2561)), 4)

    def test_the_refusal_names_each_field_over_its_limit(self):
        with self.assertRaises(C.LifecycleError) as caught:
            K.check_credential_fields(NAME, 'u' * 514, 'c' * 271, 80)
        self.assertEqual(str(caught.exception), "CREDENTIAL_FIELD_LIMIT: the entry 'AIEH synthetic entry' does not fit a "
                         'Windows generic credential: UserName is 514 characters, over CRED_MAX_USERNAME_LENGTH '
                         '(256+1+256); Comment is 271 characters, over CRED_MAX_STRING_LENGTH (256); nothing was written')

    def test_the_check_writes_nothing(self):
        with mock.patch.object(K, 'CredentialStore', UntouchableStore):
            K.check_credential_fields(NAME, 'u', 'a comment', 80)
            with self.assertRaises(C.LifecycleError) as caught:
                K.check_credential_fields('T' * 40000, 'u', 'c', 80)
        self.assertIn("'" + 'T' * 80 + "'", caught.exception.detail)  # the name is cut at 80 characters
        self.assertNotIn('T' * 81, caught.exception.detail)


class TestFakeProvider(ProviderContract, WindowsFieldLimits, unittest.TestCase):
    def make(self):
        return MemoryProvider()

    def entries_named(self, provider, name):
        return int(name in provider.entries)

    def attempts(self, provider):
        return len(provider.entries)


@windows_only
class TestWindowsProvider(ProviderContract, WindowsFieldLimits, unittest.TestCase):
    def make(self):
        return K.WindowsCredentialProvider(windows_store())

    def entries_named(self, provider, name):
        return int(name in provider.store._adv.entries)

    def attempts(self, provider):
        return provider.store._adv.writes

    def test_a_write_that_fits_can_still_fail_with_its_own_code(self):
        # The limits are no guarantee: CredWriteW's own refusal (1734, as on 2026-11-11) stays a write failure.
        provider = K.WindowsCredentialProvider(windows_store(1734))
        with self.assertRaises(C.LifecycleError) as caught:
            provider.set(NAME, 'aieh-synthetic-user', 'synthetic-value', 'a comment that fits')
        self.assertEqual((caught.exception.code, caught.exception.refusal), ('CREDENTIAL_WRITE_FAILED', False))
        self.assertIn('failed (1734)', caught.exception.detail)
        self.assertEqual(provider.store._adv.writes, 1)

    def test_stored_as_a_generic_utf16_credential_persisted_per_machine(self):
        provider = self.make()
        provider.set(NAME, 'aieh-synthetic-user', SECRET, 'a synthetic comment')
        user, blob, comment, kind, persist = provider.store._adv.entries[NAME]
        self.assertEqual((user, blob, comment), ('aieh-synthetic-user', SECRET.encode('utf-16-le'),
                                                 'a synthetic comment'))
        self.assertEqual((kind, persist), (K.CredentialStore.GENERIC, K.CredentialStore.PERSIST_LOCAL_MACHINE))
        provider.get(NAME)
        self.assertEqual(provider.store._adv.freed, 1)  # every read is freed

    def test_no_logon_session_is_the_provider_locked(self):
        store = windows_store(K.CredentialStore.ERROR_NO_SUCH_LOGON_SESSION)
        for call in (lambda: store.read('AIEH synthetic'), lambda: store.write('AIEH synthetic', 'u', b'x', ''),
                     lambda: store.delete('AIEH synthetic')):
            with self.assertRaises(C.LifecycleError) as caught:
                call()
            self.assertEqual((caught.exception.code, caught.exception.refusal), ('CREDENTIAL_PROVIDER_LOCKED', True))

    def test_not_found_and_other_errors_keep_their_meaning(self):
        store = windows_store(K.CredentialStore.ERROR_NOT_FOUND)
        self.assertIsNone(store.read('AIEH synthetic'))
        self.assertFalse(store.delete('AIEH synthetic'))
        store = windows_store(5)
        for call, code in ((lambda: store.read('AIEH synthetic'), 'CREDENTIAL_READ_FAILED'),
                           (lambda: store.write('AIEH synthetic', 'u', b'x', ''), 'CREDENTIAL_WRITE_FAILED'),
                           (lambda: store.delete('AIEH synthetic'), 'CREDENTIAL_DELETE_FAILED')):
            with self.assertRaises(C.LifecycleError) as caught:
                call()
            self.assertEqual((caught.exception.code, caught.exception.refusal), (code, False))


class TestKeyringProvider(ProviderContract, unittest.TestCase):
    def make(self):
        return keyring_provider()

    def entries_named(self, provider, name):
        return sum(1 for service, _user in provider.backend.entries if service == name)

    def tearDown(self):
        MemoryKeyring.locked = False

    def test_the_entry_is_the_service_its_user_name_and_its_password(self):
        provider = self.make()
        provider.set(NAME, 'aieh-synthetic-user', SECRET, 'a comment keyring cannot store')
        self.assertEqual(provider.backend.entries, {(NAME, 'aieh-synthetic-user'): SECRET})

    def test_keyring_errors_become_stable_codes_without_their_message(self):
        provider = self.make()
        provider.set(NAME, 'aieh-synthetic-user', SECRET)
        MemoryKeyring.locked = True
        for call in (lambda: provider.get(NAME), lambda: provider.set(NAME, 'u', 'v'), lambda: provider.delete(NAME)):
            with self.assertRaises(C.LifecycleError) as caught:
                call()
            self.assertEqual((caught.exception.code, caught.exception.refusal), ('CREDENTIAL_PROVIDER_LOCKED', True))
            self.assertNotIn('the collection is locked', str(caught.exception))
        MemoryKeyring.locked = False
        provider.backend.delete_password = mock.Mock(side_effect=keyring.errors.PasswordDeleteError(SECRET))
        with self.assertRaises(C.LifecycleError) as caught:
            provider.delete(NAME)
        self.assertEqual((caught.exception.code, caught.exception.refusal), ('CREDENTIAL_DELETE_FAILED', False))
        self.assertNotIn(SECRET, str(caught.exception))


# ---------------------------------------------------------------- the factory


def forbidden_import(name):
    raise AssertionError(f'the factory imported {name}')


class TestFactory(unittest.TestCase):
    def refused(self, *args, **kwargs) -> C.LifecycleError:
        with self.assertRaises(C.LifecycleError) as caught:
            K.select_provider(*args, **kwargs)
        self.assertEqual((caught.exception.code, caught.exception.refusal), ('NO_CREDENTIAL_PROVIDER', True))
        self.assertIn('remedy:', str(caught.exception))
        return caught.exception

    def test_windows_is_credential_manager_and_keyring_is_never_imported(self):
        store = SimpleNamespace(read=None, write=None, delete=None)
        provider = K.select_provider('Windows', import_module=forbidden_import, windows_store=lambda: store)
        self.assertIsInstance(provider, K.WindowsCredentialProvider)
        self.assertIs(provider.store, store)
        self.assertEqual(K.describe(provider)['provider'], 'windows-credential-manager')

    @windows_only
    def test_on_this_windows_host_the_real_factory_loads_credential_manager_only(self):
        provider = K.select_provider(import_module=forbidden_import)  # the running system; no entry is read
        self.assertIsInstance(provider, K.WindowsCredentialProvider)
        self.assertIsInstance(provider.store, K.CredentialStore)

    def test_credential_manager_not_loadable_is_refused(self):
        def unloadable():
            raise OSError(126, 'advapi32 is not loadable')
        self.assertIn('advapi32', self.refused('Windows', windows_store=unloadable).detail)

    def test_an_unknown_system_is_refused(self):
        self.assertIn("'Plan9'", self.refused('Plan9', import_module=forbidden_import).detail)

    def test_each_posix_system_instantiates_its_own_backend_explicitly(self):
        for system, module in (('Linux', 'keyring.backends.SecretService'), ('Darwin', 'keyring.backends.macOS')):
            hook = backend_module(MemoryKeyring)
            with self.subTest(system=system):
                provider = K.select_provider(system, import_module=hook)
                self.assertIsInstance(provider, K.KeyringProvider)
                self.assertIs(type(provider.backend), MemoryKeyring)
                self.assertEqual(hook.imported, [module, 'keyring.backend'])
                self.assertEqual(K.describe(provider)['provider'], K.KEYRING_BACKENDS[system]['provider'])
                self.assertEqual(provider.priority, 1)

    def test_keyring_not_importable_is_refused_naming_the_tools_venv(self):
        def missing(name):
            raise ModuleNotFoundError(f'No module named {name!r}', name='keyring')
        for system in ('Linux', 'Darwin'):
            with self.subTest(system=system):
                self.assertIn('task tools:install', self.refused(system, import_module=missing).detail)

    def test_a_backend_whose_priority_is_not_viable_is_refused(self):
        def raising(cls):
            raise RuntimeError('The Secret Service daemon is neither running nor activatable through D-Bus')
        cases = {'raises': property(raising), 'zero': 0, 'negative': -1, 'a boolean': True, 'not a number': '5'}
        for label, priority in cases.items():
            backend = type('Candidate', (MemoryKeyring,), {'priority': priority})
            with self.subTest(priority=label):
                error = self.refused('Linux', import_module=backend_module(backend))
                self.assertIn('not viable', error.detail)

    def test_a_backend_that_cannot_find_an_entry_by_its_name_alone_is_refused(self):
        backend = type('NoNameLookup', (MemoryKeyring,), {'get_credential': keyring.backend.KeyringBackend.get_credential})
        self.assertIn('by its name alone', self.refused('Darwin', import_module=backend_module(backend)).detail)

    @windows_only
    def test_the_real_keyring_backends_are_not_viable_on_this_windows_host(self):
        # keyring's own classes, instantiated explicitly; neither is viable on Windows, and neither is
        # WinVaultKeyring ever considered.
        detail = self.refused('Linux').detail
        self.assertIn('keyring.backends.SecretService.Keyring is not viable here: its priority raised RuntimeError',
                      detail)
        detail = self.refused('Darwin').detail
        self.assertIn('keyring.backends.macOS.Keyring is not viable here: its priority raised RuntimeError: macOS '
                      'required', detail)


class TestKeyringConfigurationIsIgnored(unittest.TestCase):
    """keyring's own selection and configuration never choose or configure the harness's backend (I6)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='aieh-credentials-'))
        (cls.tmp / 'keyringrc.cfg').write_text('[backend]\ndefault-keyring=keyring.backends.fail.Keyring\n',
                                               encoding='utf-8')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.env = {'PYTHON_KEYRING_BACKEND': 'keyring.backends.null.Keyring',
                    'KEYRING_PROPERTY_SCHEME': 'KeePassXC', 'KEYRING_PROPERTY_PREFERRED_COLLECTION': '/elsewhere'}
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.dict(os.environ, self.env))
        stack.enter_context(mock.patch.object(keyring.util.platform_, 'config_root', return_value=self.tmp))
        before = keyring.core._keyring_backend
        self.addCleanup(setattr, keyring.core, '_keyring_backend', before)

    def test_keyring_would_choose_otherwise_and_the_factory_never_asks_it(self):
        # The trap is armed: keyring's own configuration names other backends.
        self.assertEqual(type(keyring.core.load_env()).__module__, 'keyring.backends.null')
        self.assertEqual(type(keyring.core.load_config()).__module__, 'keyring.backends.fail')
        traps = {name: mock.Mock(side_effect=AssertionError(f'keyring.core.{name} was used'))
                 for name in ('get_keyring', 'init_backend', 'load_env', 'load_config', '_detect_backend',
                              'load_keyring', 'set_keyring')}
        with contextlib.ExitStack() as stack:
            for name, trap in traps.items():
                stack.enter_context(mock.patch.object(keyring.core, name, trap))
            stack.enter_context(mock.patch.object(keyring, 'get_keyring', traps['get_keyring']))
            for name in ('get_all_keyring', '_load_plugins'):  # keyrings.alt and other plug-ins load here
                stack.enter_context(mock.patch.object(keyring.backend, name,
                                                      mock.Mock(side_effect=AssertionError(name))))
            stack.enter_context(mock.patch('subprocess.Popen', side_effect=AssertionError('the keyring CLI')))
            provider = keyring_provider()
            provider.set(NAME, 'aieh-synthetic-user', SECRET)
            self.assertEqual(provider.get(NAME), ('aieh-synthetic-user', SECRET))
            self.assertTrue(provider.delete(NAME))
        self.assertIs(type(provider.backend), MemoryKeyring)
        self.assertFalse(any(trap.called for trap in traps.values()))
        self.assertNotIn('keyrings', sys.modules)

    def test_keyring_property_environment_variables_are_cleared_and_named(self):
        class Selectable(keyring.backend.SchemeSelectable, MemoryKeyring):
            pass
        provider = K.qualify_keyring('Linux', import_module=backend_module(Selectable))
        self.assertEqual(vars(provider.backend), {'entries': {}})  # the backend's own state stays
        self.assertEqual(provider.backend.scheme, 'default')  # not KeePassXC from the environment
        self.assertEqual(provider.ignored, ('KEYRING_PROPERTY_PREFERRED_COLLECTION', 'KEYRING_PROPERTY_SCHEME'))
        self.assertEqual(K.describe(provider)['ignored_environment_configuration'], list(provider.ignored))
        provider.set(NAME, 'aieh-synthetic-user', SECRET)
        self.assertEqual(provider.backend._query(NAME, 'aieh-synthetic-user'),
                         {'service': NAME, 'username': 'aieh-synthetic-user'})

    def test_a_keychain_taken_from_the_environment_is_cleared(self):
        class KeychainTaking(MemoryKeyring):
            keychain = '/a/keychain/from/the/environment'  # as macOS.Keyring takes KEYCHAIN_PATH at import
        provider = K.qualify_keyring('Darwin', import_module=backend_module(KeychainTaking))
        self.assertIsNone(provider.backend.keychain)
        self.assertIn('keyring.backends.macOS.Keyring.keychain (from the environment)', provider.ignored)


class TestSource(unittest.TestCase):
    """What the module's own code can reach, read from its syntax tree."""

    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(SOURCE.read_text(encoding='utf-8'))

    def test_no_keyring_selection_configuration_cli_or_plugin_is_reachable(self):
        names = {node.attr for node in ast.walk(self.tree) if isinstance(node, ast.Attribute)}
        names |= {node.id for node in ast.walk(self.tree) if isinstance(node, ast.Name)}
        for forbidden in ('get_keyring', 'init_backend', 'load_config', 'load_env', 'load_keyring', 'set_keyring',
                          'get_all_keyring', '_load_plugins', 'get_password', 'disable'):
            self.assertNotIn(forbidden, names)
        imports = {alias.name for node in ast.walk(self.tree) if isinstance(node, ast.Import) for alias in node.names}
        imports |= {node.module for node in ast.walk(self.tree) if isinstance(node, ast.ImportFrom)}
        self.assertFalse({name for name in imports if name and name.split('.')[0] in ('keyring', 'keyrings')})
        self.assertNotIn('subprocess', imports)
        modules = {node.value for node in ast.walk(self.tree) if isinstance(node, ast.Constant)
                   and isinstance(node.value, str) and re.fullmatch(r'keyrings?(\.\w+)+', node.value)}
        self.assertEqual(modules, {'keyring.backends.SecretService', 'keyring.backends.macOS', 'keyring.backend'})


# ---------------------------------------------------------------- doctor


class UntouchableStore:
    """A Credential Manager stand-in that fails the test on any entry access."""

    def __getattr__(self, name):
        raise AssertionError(f'doctor touched the store ({name})')


class TestDoctor(unittest.TestCase):
    def test_a_viable_provider_without_touching_any_entry(self):
        report = K.doctor('Windows', windows_store=UntouchableStore, import_module=forbidden_import)
        self.assertEqual((report['format'], report['system'], report['viable'], report['refusal']),
                         ('aieh-credential-doctor/1', 'Windows', True, None))
        self.assertEqual(report['provider'], 'windows-credential-manager')
        self.assertEqual(report['entries_touched'], 0)
        self.assertEqual(len(report['never_used']), 5)

    def test_a_keyring_provider_reports_its_backend_and_priority(self):
        report = K.doctor('Linux', import_module=backend_module(MemoryKeyring))
        self.assertEqual((report['provider'], report['priority'], report['viable']),
                         ('keyring-secret-service', 1, True))
        self.assertTrue(report['backend'].endswith('.MemoryKeyring'))
        self.assertTrue(report['keyring_imported'])

    def test_no_qualified_provider_is_reported_with_its_refusal(self):
        report = K.doctor('Plan9')
        self.assertEqual((report['provider'], report['viable'], report['refusal']['code']),
                         (None, False, 'NO_CREDENTIAL_PROVIDER'))
        self.assertTrue(report['refusal']['remedy'])

    def run_main(self, system):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(K._platform, 'system', return_value=system), \
                mock.patch.object(K, 'CredentialStore', UntouchableStore), \
                mock.patch('sys.stdout', out), mock.patch('sys.stderr', err):
            code = K.main(['doctor'])
        return code, json.loads(out.getvalue()), err.getvalue()

    def test_the_command_line_exits_0_viable_2_refused_and_scans_its_output(self):
        code, report, err = self.run_main('Windows')
        self.assertEqual((code, report['viable']), (0, True))
        self.assertIn('I7 no-exposure scan: clean', err)
        code, report, err = self.run_main('Plan9')
        self.assertEqual((code, report['refusal']['code']), (2, 'NO_CREDENTIAL_PROVIDER'))
        self.assertIn('I7 no-exposure scan: clean', err)


if __name__ == '__main__':
    unittest.main()
