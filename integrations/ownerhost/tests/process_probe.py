"""Read-only observations of another process of this account, for the listener tests (Windows): its environment
block and its command line, read from its process parameters with the documented native query
(NtQueryInformationProcess, ProcessBasicInformation) and ReadProcessMemory. Nothing is written to the process.

These are the outside view of the Integration process: what the test reads here is what the process holds, not what
it reports about itself. The offsets are those of a 64-bit process on Windows 8 and later (PEB.ProcessParameters at
0x20; RTL_USER_PROCESS_PARAMETERS.CommandLine at 0x70, Environment at 0x80, EnvironmentSize at 0x3F0).
"""
from __future__ import annotations

import ctypes
import os
import struct
from ctypes import wintypes

PROCESS_QUERY_INFORMATION, PROCESS_VM_READ = 0x0400, 0x0010
PARAMETERS_AT, COMMAND_LINE_AT, ENVIRONMENT_AT, ENVIRONMENT_SIZE_AT = 0x20, 0x70, 0x80, 0x3F0
AVAILABLE = os.name == 'nt' and struct.calcsize('P') == 8


class _BasicInformation(ctypes.Structure):
    _fields_ = [('ExitStatus', ctypes.c_long), ('PebBaseAddress', ctypes.c_void_p),
                ('AffinityMask', ctypes.c_void_p), ('BasePriority', ctypes.c_long),
                ('UniqueProcessId', ctypes.c_void_p), ('InheritedFromUniqueProcessId', ctypes.c_void_p)]


def _apis():
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    ntdll = ctypes.WinDLL('ntdll')
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k32.ReadProcessMemory.argtypes = (wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                                      ctypes.POINTER(ctypes.c_size_t))
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    ntdll.NtQueryInformationProcess.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.ULONG,
                                                ctypes.POINTER(wintypes.ULONG))
    ntdll.NtQueryInformationProcess.restype = ctypes.c_long
    return k32, ntdll


def _read(k32, handle, address: int, size: int) -> bytes:
    buffer = ctypes.create_string_buffer(size)
    done = ctypes.c_size_t(0)
    if not k32.ReadProcessMemory(handle, ctypes.c_void_p(address), buffer, size, ctypes.byref(done)) \
            or done.value != size:
        raise OSError(ctypes.get_last_error(), f'ReadProcessMemory({address:#x}, {size}) failed')
    return buffer.raw


def parameters(pid: int) -> dict:
    """{'environment': {name: value}, 'command_line': str} of process PID (64-bit, this account)."""
    if not AVAILABLE:
        raise OSError('a 64-bit Windows process is needed')
    k32, ntdll = _apis()
    handle = k32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, int(pid))
    if not handle:
        raise OSError(ctypes.get_last_error(), f'OpenProcess({pid}) failed')
    try:
        info = _BasicInformation()
        status = ntdll.NtQueryInformationProcess(handle, 0, ctypes.byref(info), ctypes.sizeof(info), None)
        if status != 0:
            raise OSError(status, 'NtQueryInformationProcess failed')
        params = struct.unpack('<Q', _read(k32, handle, info.PebBaseAddress + PARAMETERS_AT, 8))[0]
        length, _maximum, _pad, buffer = struct.unpack('<HHIQ', _read(k32, handle, params + COMMAND_LINE_AT, 16))
        command_line = _read(k32, handle, buffer, length).decode('utf-16-le') if length else ''
        block = struct.unpack('<Q', _read(k32, handle, params + ENVIRONMENT_AT, 8))[0]
        size = struct.unpack('<Q', _read(k32, handle, params + ENVIRONMENT_SIZE_AT, 8))[0]
        text = _read(k32, handle, block, size).decode('utf-16-le', 'replace')
    finally:
        k32.CloseHandle(handle)
    environment = {}
    for entry in text.split('\0'):
        if not entry:
            break
        name, sep, value = entry[1:].partition('=')     # a name may start with '=' (the drive variables)
        environment[entry[0] + name if sep else entry] = value
    return {'environment': environment, 'command_line': command_line}
