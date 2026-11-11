"""Tests of the shared no-window helper (integrations/platform/no_window.py; the Owner's rule of 2026-11-11).

The console state is injected, so each answer is checked on every host: CREATE_NO_WINDOW only on Windows
and only where the process is attached to no console. Nothing is started.
"""
from __future__ import annotations

import ctypes
import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

CATEGORY = 'unit'

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('aieh_no_window_under_test', HERE.parent / 'no_window.py')
N = importlib.util.module_from_spec(spec)
spec.loader.exec_module(N)
WINDOWS_FLAG = 0x08000000      # CREATE_NO_WINDOW


class TestFlags(unittest.TestCase):
    def test_windows_without_a_console_gets_the_flag(self):
        with mock.patch.object(N, 'WINDOWS', True), mock.patch.object(N, 'CREATE_NO_WINDOW', WINDOWS_FLAG):
            self.assertEqual(N.no_window_flags(attached=False), WINDOWS_FLAG)
            with mock.patch.object(N, 'attached_to_console', return_value=False):
                self.assertEqual(N.no_window_flags(), WINDOWS_FLAG)

    def test_windows_with_a_console_gets_none(self):
        """A child shares an attached console, with or without a window, and opens no window of its own."""
        with mock.patch.object(N, 'WINDOWS', True), mock.patch.object(N, 'CREATE_NO_WINDOW', WINDOWS_FLAG):
            self.assertEqual(N.no_window_flags(attached=True), 0)
            with mock.patch.object(N, 'attached_to_console', return_value=True):
                self.assertEqual(N.no_window_flags(), 0)

    def test_off_windows_there_are_no_creation_flags(self):
        with mock.patch.object(N, 'WINDOWS', False):
            self.assertEqual((N.no_window_flags(attached=False), N.no_window_flags(attached=True)), (0, 0))
            self.assertTrue(N.attached_to_console())

    def test_the_constant_is_the_platforms(self):
        self.assertEqual(N.CREATE_NO_WINDOW, getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if sys.platform == 'win32':
            self.assertEqual(N.CREATE_NO_WINDOW, WINDOWS_FLAG)


class TestConsoleState(unittest.TestCase):
    def test_the_state_is_the_console_process_count(self):
        """GetConsoleProcessList counts the processes attached to this process's console (at least itself);
        0 means no console. Its answer is stood in for, so both states are checked on any host."""
        for count, attached in ((0, False), (1, True), (3, True)):
            seen = []

            def process_list(buffer, size, count=count):
                seen.append((ctypes.sizeof(buffer), size))
                return count
            with self.subTest(count=count), mock.patch.object(N, 'WINDOWS', True), \
                    mock.patch.object(N, '_PROCESS_LIST', [process_list]):
                self.assertIs(N.attached_to_console(), attached)
                self.assertEqual(seen, [(4, 1)])

    @unittest.skipUnless(sys.platform == 'win32', 'the Windows console API')
    def test_the_real_call_answers(self):
        self.assertIsInstance(N.attached_to_console(), bool)


if __name__ == '__main__':
    unittest.main()
