"""Tests of the Windows adapter of the host-service lifecycle contract (plan leaf F-06.2).

The unit classes check what the adapter declares and its refusals with fakes: the supervision's flag
checks, and that it supplies the Credential Manager provider through the harness's factory (the provider and
its error mapping moved to integrations/credentials in plan leaf F-06.3, whose tests cover them; the real
Credential Manager is never called). The integration class reads this process's own listener, token and
identity through the adapter, without launching anything; the Job Object itself is exercised against child
processes by integrations/gitea/tests/test_gitea_host.py (TestJobObject), through the same code.
"""
from __future__ import annotations

import importlib.util
import os
import socket
import sys
import unittest
from pathlib import Path

CATEGORY = 'unit'

HERE = Path(__file__).resolve().parent
WINDOWS = sys.platform == 'win32'


def _load(name, path):
    if (module := sys.modules.get(name)) is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = sys.modules[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


C = _load('aieh_platform_contract', HERE.parent / 'platform_contract.py')
W = _load('aieh_platform_windows', HERE.parent / 'platform_windows.py')
windows_only = unittest.skipUnless(WINDOWS, 'Windows API')


class TestDeclaration(unittest.TestCase):
    def test_what_the_adapter_declares(self):
        adapter = W.WindowsAdapter('AMD64')
        self.assertIsInstance(adapter, C.PlatformAdapter)
        self.assertEqual((adapter.system, adapter.asset_key), ('Windows', 'windows-amd64'))
        self.assertEqual(adapter.supervision['mechanism'], 'job-object')
        self.assertIn('JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE', adapter.supervision['detail'])
        self.assertTrue(adapter.supervision['ends_on'] and adapter.supervision['limit'])
        self.assertEqual(adapter.credentials['provider'], 'windows-credential-manager')
        self.assertTrue(adapter.verified_bytes.startswith('started-bytes'))
        self.assertIs(C.LifecycleError, W.LifecycleError)  # one error kind across the contract and the adapter

    def test_no_psutil(self):
        source = (HERE.parent / 'platform_windows.py').read_text(encoding='utf-8')
        self.assertNotIn('import psutil', source)
        self.assertNotIn('psutil', sys.modules)


class FakeJob:
    def __init__(self, flags=W.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, fail=None):
        self.flags, self.fail, self.assigned = flags, fail, False

    def assign_current(self):
        if self.fail == 'assign':
            raise OSError(5, 'AssignProcessToJobObject(current) failed')
        self.assigned = True

    def limit_flags(self):
        return self.flags

    def contains(self, handle):
        return handle == 'child'


class TestSupervision(unittest.TestCase):
    def test_a_kill_on_close_job_without_breakaway(self):
        supervision = W.JobSupervision(lambda: FakeJob())
        self.assertTrue(supervision.job.assigned)
        # The run record's 'job' entry, exactly as F-06.1 wrote it.
        self.assertEqual(supervision.report(), {'limit_flags': '0x2000', 'kill_on_job_close': True,
                                                'breakaway_allowed': False})
        self.assertTrue(supervision.contains('child'))

    def test_unsafe_flags_are_refused(self):
        for flags in (0, W.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | W.JOB_OBJECT_LIMIT_BREAKAWAY_OK,
                      W.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | W.JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK):
            with self.subTest(flags=hex(flags)), self.assertRaises(C.LifecycleError) as caught:
                W.JobSupervision(lambda: FakeJob(flags))
            self.assertEqual((caught.exception.code, caught.exception.refusal), ('JOB_UNSAFE', False))

    def test_no_job_is_supervision_unavailable(self):
        def no_job():
            raise OSError(5, 'CreateJobObjectW failed')
        for factory in (no_job, lambda: FakeJob(fail='assign')):
            with self.assertRaises(C.LifecycleError) as caught:
                W.JobSupervision(factory)
            self.assertEqual(caught.exception.code, 'SUPERVISION_UNAVAILABLE')
            self.assertIn('remedy:', str(caught.exception))


@windows_only
class TestCredentialProvider(unittest.TestCase):
    def test_the_adapter_supplies_the_credential_manager_provider(self):
        provider = W.WindowsAdapter('AMD64').credential_provider()
        self.assertIsInstance(provider, W.credentials.WindowsCredentialProvider)
        self.assertIsInstance(provider, C.CredentialProvider)


@windows_only
class TestInspection(unittest.TestCase):
    """This process's own listener, token and identity, through the adapter (no process launched)."""
    category = 'integration'

    def test_listener_identity_and_port(self):
        adapter = C.select_adapter()
        self.assertEqual(adapter.asset_key, C.asset_key('Windows', adapter.machine))
        tcp = socket.socket()
        tcp.bind(('127.0.0.1', 0))
        tcp.listen()
        try:
            port = tcp.getsockname()[1]
            self.assertIn({'proto': 'tcp', 'family': 'ipv4', 'address': '127.0.0.1', 'port': port, 'pid': os.getpid()},
                          adapter.listeners(os.getpid()))
            self.assertTrue(adapter.port_in_use(port, '127.0.0.1'))
        finally:
            tcp.close()
        identity = adapter.user_identity(os.getpid())
        self.assertEqual(set(identity), {'elevated', 'elevation_type', 'integrity_rid'})
        me = adapter.process(os.getpid())
        self.assertEqual(adapter.process_maybe(os.getpid(), me.created()).pid, os.getpid())
        self.assertIsNone(adapter.process_maybe(os.getpid(), me.created() + 1))


if __name__ == '__main__':
    unittest.main()
