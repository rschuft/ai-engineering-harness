"""The throwaway-name cross-read test (plan leaf F-06.3): an entry written through a provider in this
process is read back by name alone in a separate process, then deleted, and its absence is checked in a
separate process again; a no-exposure scan (I7) of everything the processes printed follows.

Default mode (TestCrossReadKeyringFile, every run): KeyringProvider over a keyring backend of this test that
keeps its entries in a JSON file of a temporary directory (crossread_support.FileKeyring), qualified by the
harness's own code; no credential store of the host is touched.

Real-store mode (TestCrossReadRealStore): opt-in only, with AIEH_CREDENTIALS_REAL_STORE=1, on Windows. It
uses the provider the harness's factory chooses there, Windows Credential Manager, with one throwaway entry:
a name 'AIEH test cross-read ' followed by 32 random hex digits, the user 'aieh-test-cross-read' and a random
non-secret value. It reads that name to check it is absent, writes it, has a child process read it, deletes
it and has a child process check its absence; it deletes it again in cleanup if a step failed. It touches
no other entry and never enumerates the store (no CredEnumerate).
"""
from __future__ import annotations

import importlib.util
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CATEGORY = 'integration'

HERE = Path(__file__).resolve().parent


def _load(name, path):
    if (module := sys.modules.get(name)) is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = sys.modules[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


S = _load('aieh_credentials_crossread_support', HERE / 'crossread_support.py')
K = S.load_credentials()
C = K.contract
OPT_IN = os.environ.get('AIEH_CREDENTIALS_REAL_STORE') == '1'
TIMEOUT = 60


class CrossRead:
    """The cross-read act over self.provider; child(name) runs the reading process."""

    def child(self, name: str) -> tuple[dict, str]:
        raise NotImplementedError

    def cross_read(self):
        name = S.PREFIX + secrets.token_hex(16)
        value = secrets.token_urlsafe(24)  # random and non-secret: it protects nothing
        guard = C.ExposureGuard()
        guard.hold(value)
        outputs = []
        self.assertIsNone(self.provider.get(name), 'a fresh random name exists already')
        self.provider.set(name, S.USER, value, 'Throwaway entry of the F-06.3 cross-read test; deleted by it.')
        try:
            read, text = self.child(name)
            outputs.append(text)
            self.assertEqual(read, {'present': True, 'user': S.USER, 'fingerprint': K.fingerprint(value)})
            self.assertTrue(self.provider.delete(name))
            gone, text = self.child(name)
            outputs.append(text)
            self.assertEqual(gone, {'present': False})
            self.assertIsNone(self.provider.get(name))
        finally:
            if self.provider.get(name) is not None:
                self.provider.delete(name)
        for index, text in enumerate(outputs):
            guard.scan_text(f'child output {index}', text)
        self.assertTrue(guard.report()['clean'], guard.report())  # I7: the value appears in no output
        guard.clear()
        return name

    def run_child(self, *args: str) -> tuple[dict, str]:
        result = subprocess.run([sys.executable, '-I', '-B', str(HERE / 'crossread_support.py'), *args],
                                capture_output=True, timeout=TIMEOUT)
        text = (result.stdout + result.stderr).decode('utf-8', 'replace')
        self.assertEqual(result.returncode, 0, text[-500:])
        return json.loads(result.stdout), text


class TestCrossReadKeyringFile(CrossRead, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='aieh-credentials-'))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.store = self.tmp / 'file-keyring.json'
        self.provider = S.file_provider(self.store)

    def child(self, name):
        return self.run_child('keyring-file', str(self.store), name)

    def test_a_separate_process_reads_the_entry_by_its_name_then_finds_it_gone(self):
        self.assertEqual(type(self.provider).__name__, 'KeyringProvider')
        name = self.cross_read()
        self.assertNotIn(name, json.loads(self.store.read_text(encoding='utf-8')))

    def test_the_child_refuses_a_name_that_is_not_a_throwaway_one(self):
        result = subprocess.run([sys.executable, '-I', '-B', str(HERE / 'crossread_support.py'), 'keyring-file',
                                 str(self.store), 'AIEH Gitea bot builder'], capture_output=True, timeout=TIMEOUT)
        self.assertEqual((result.returncode, result.stdout), (2, b''))


@unittest.skipUnless(OPT_IN and sys.platform == 'win32',
                     'the real-store cross-read is opt-in: AIEH_CREDENTIALS_REAL_STORE=1, on Windows')
class TestCrossReadRealStore(CrossRead, unittest.TestCase):
    """One throwaway Credential Manager entry, written, read by a separate process, deleted, checked absent."""
    category = 'e2e'

    def setUp(self):
        self.provider = K.select_provider('Windows')
        self.assertEqual(type(self.provider).__name__, 'WindowsCredentialProvider')

    def child(self, name):
        return self.run_child('windows', name)

    def test_credential_manager_cross_read_with_one_throwaway_entry(self):
        self.cross_read()


if __name__ == '__main__':
    unittest.main()
