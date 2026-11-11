"""Creation flags that keep a started process from opening a console window (the Owner's rule of
2026-11-11), at no cost where no window can open.

A console process started without creation flags shares its parent's console, so it opens no window of
its own whenever the parent is attached to a console: one with a visible window, a pseudo console (ConPTY,
as in Windows Terminal) or a console with no window (a parent itself started with CREATE_NO_WINDOW). Only
a parent attached to no console (started with DETACHED_PROCESS, a GUI process, or after FreeConsole)
gives a console child a console of its own, which opens a window unless the child is started with
CREATE_NO_WINDOW. CREATE_NO_WINDOW is not free: each child then gets a console host of its own, about
7 ms per launch on the verification host (Windows 11, 2026-11-11).

``no_window_flags()`` is therefore CREATE_NO_WINDOW on Windows when this process is attached to no console,
and 0 when it is attached to one (its children share that console) and off Windows. Long-lived background
starts whose window state must never depend on their parent (QEMU, the Gitea supervisor and Gitea, the
inference forward holder) pass CREATE_NO_WINDOW unconditionally instead. Never DETACHED_PROCESS or
CREATE_NEW_CONSOLE. ``tools/tests/test_launch_census.py`` checks that every launch of the harness uses
one or the other.

Standard library only; loaded by path (``spec_from_file_location``) by the modules of tools/,
integrations/ and composition/ that start processes.
"""
from __future__ import annotations

import os
import subprocess

CREATE_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
WINDOWS = os.name == 'nt'
_PROCESS_LIST = []      # kernel32.GetConsoleProcessList, bound on first use


def attached_to_console() -> bool:
    """Whether this process is attached to a console (with a window or without one). Off Windows: True
    (no console window is ever created for a child there)."""
    if not WINDOWS:
        return True
    import ctypes
    if not _PROCESS_LIST:
        function = ctypes.WinDLL('kernel32', use_last_error=True).GetConsoleProcessList
        function.restype, function.argtypes = ctypes.c_uint32, (ctypes.POINTER(ctypes.c_uint32), ctypes.c_uint32)
        _PROCESS_LIST.append(function)
    # The number of processes attached to this process's console (at least itself), or 0 with no console.
    return _PROCESS_LIST[0]((ctypes.c_uint32 * 1)(), 1) > 0


def no_window_flags(attached: bool | None = None) -> int:
    """The creation flags for a child that must open no console window: CREATE_NO_WINDOW on Windows when
    this process is attached to no console, else 0. ``attached`` stands in for the console state in tests."""
    if not WINDOWS:
        return 0
    if attached is None:
        attached = attached_to_console()
    return 0 if attached else CREATE_NO_WINDOW
