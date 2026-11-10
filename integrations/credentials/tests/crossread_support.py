"""Support for the throwaway-name cross-read test (test_crossread.py; plan leaf F-06.3), and the child process
it runs: one process writes an entry through a provider, a separate process reads it back by name alone.

The child prints what it read as JSON: whether the entry is present, its user and the fingerprint of its
value, never the value (I1, I8). It is given the entry's name only; the value never reaches its command line
or environment.

  <python> -I -B crossread_support.py keyring-file <store file> <entry name>
  <python> -I -B crossread_support.py windows <entry name>

keyring-file is the default mode: the provider is KeyringProvider over FileKeyring, a keyring backend of
this test only that keeps entries in a JSON file of the test's temporary directory, so that two processes
share it (the harness itself has no file store: decision 0011 section 3). The backend goes through the
harness's own qualification (credential_provider.qualify_keyring), as SecretService.Keyring would.
windows is the opt-in real-store mode: the provider is the one the harness's factory chooses on Windows,
Credential Manager.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
PREFIX = 'AIEH test cross-read '  # every throwaway entry's name: this prefix and 32 random hex digits
USER = 'aieh-test-cross-read'


def load_credentials():
    if (module := sys.modules.get('aieh_credential_provider')) is None:
        spec = importlib.util.spec_from_file_location('aieh_credential_provider',
                                                      HERE.parent / 'credential_provider.py')
        module = sys.modules['aieh_credential_provider'] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


def file_keyring_class():
    """FileKeyring: a keyring backend of this test that keeps its entries in FileKeyring.path (JSON)."""
    from keyring.backend import KeyringBackend
    from keyring.credentials import SimpleCredential
    from keyring.errors import PasswordDeleteError

    class FileKeyring(KeyringBackend):
        path: Path | None = None
        priority = 1

        def _read(self) -> dict:
            return json.loads(self.path.read_text(encoding='utf-8')) if self.path.is_file() else {}

        def _write(self, entries: dict) -> None:
            self.path.write_text(json.dumps(entries), encoding='utf-8')

        def get_password(self, service, username):
            entry = self._read().get(service)
            return entry[1] if entry and entry[0] == username else None

        def set_password(self, service, username, password):
            entries = self._read()
            entries[service] = [username, password]
            self._write(entries)

        def delete_password(self, service, username):
            entries = self._read()
            if service not in entries or entries[service][0] != username:
                raise PasswordDeleteError('no such password')
            del entries[service]
            self._write(entries)

        def get_credential(self, service, username):
            entry = self._read().get(service)
            if entry is None or (username is not None and entry[0] != username):
                return None
            return SimpleCredential(entry[0], entry[1])

    return FileKeyring


def file_provider(path: Path):
    """KeyringProvider over FileKeyring at path, qualified by the harness's own code (Linux's slot)."""
    credentials = load_credentials()
    backend_class = file_keyring_class()
    backend_class.path = Path(path)

    def import_module(name):
        if name == credentials.KEYRING_BACKENDS['Linux']['module']:
            return SimpleNamespace(Keyring=backend_class)
        return importlib.import_module(name)
    return credentials.qualify_keyring('Linux', import_module=import_module)


def main(argv: list[str]) -> int:
    credentials = load_credentials()
    if argv[:1] == ['keyring-file'] and len(argv) == 3:
        provider, name = file_provider(Path(argv[1])), argv[2]
    elif argv[:1] == ['windows'] and len(argv) == 2:
        provider, name = credentials.select_provider('Windows'), argv[1]
    else:
        sys.stderr.write('usage: crossread_support.py keyring-file <store file> <name> | windows <name>\n')
        return 2
    if not name.startswith(PREFIX):
        sys.stderr.write('refused: not a throwaway entry name\n')
        return 2
    entry = provider.get(name)
    result = {'present': entry is not None}
    if entry is not None:
        result.update(user=entry[0], fingerprint=credentials.fingerprint(entry[1]))
    del entry
    sys.stdout.write(json.dumps(result) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
