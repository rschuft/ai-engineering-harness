"""The Windows adapter of the host-service lifecycle contract (plan leaf F-06.2; extracted unchanged from
integrations/gitea/gitea_host.py of plan leaf F-06.1).

- Supervision: the managed environment's supervisor puts itself into a new Job Object with
  JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE before it starts the service, and holds the job's only handle:
  whenever the supervisor ends, cleanly or killed, the kernel closes that handle and ends every process
  in the job. Breakaway is not allowed.
- Process identity: a process id opened for query, wait and terminate, identified by its creation time.
- Listeners: the kernel's TCP and UDP tables (GetExtendedTcpTable, GetExtendedUdpTable), with the owning
  process of each row.
- User identity: the process token's elevation, elevation type and integrity level.
- Verified bytes: a binary is hashed through a handle that shares read only (no writer, rename or delete
  while it is held), and the process is started while that handle is held.
- Credentials: Windows Credential Manager generic credentials (CredWriteW, CredReadW, CredDeleteW).

Everything goes through the standard library's ctypes; psutil is not used. The Windows API is loaded
only when a function is called, so the module imports on any platform.
"""
from __future__ import annotations

import contextlib
import importlib.util
import os
import socket
import struct
import subprocess
import sys
from pathlib import Path

HERE = Path(os.path.realpath(__file__)).parent


def _load_contract():
    if (module := sys.modules.get('aieh_platform_contract')) is None:
        spec = importlib.util.spec_from_file_location('aieh_platform_contract', HERE / 'platform_contract.py')
        module = sys.modules['aieh_platform_contract'] = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except BaseException:
            del sys.modules['aieh_platform_contract']
            raise
    return module


contract = _load_contract()
LifecycleError = contract.LifecycleError


# ---------------------------------------------------------------- processes and jobs


def _k32():
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.OpenProcess.restype = wintypes.HANDLE
    k.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k.CloseHandle.argtypes = (wintypes.HANDLE,)
    k.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
    k.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    k.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    k.WaitForSingleObject.restype = wintypes.DWORD
    k.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
    k.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                             ctypes.POINTER(wintypes.DWORD))
    k.CreateJobObjectW.restype = wintypes.HANDLE
    k.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
    k.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD)
    k.QueryInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
                                            ctypes.POINTER(wintypes.DWORD))
    k.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    k.IsProcessInJob.argtypes = (wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL))
    k.GetCurrentProcess.restype = wintypes.HANDLE
    return k


class Proc:
    """One process id, opened for query, wait and terminate; identified by its creation time."""
    SYNCHRONIZE, TERMINATE, QUERY_LIMITED = 0x00100000, 0x0001, 0x1000
    STILL_ACTIVE = 259

    def __init__(self, pid: int):
        import ctypes
        self._ct, self._k, self.pid = ctypes, _k32(), int(pid)
        self.handle = self._k.OpenProcess(self.SYNCHRONIZE | self.TERMINATE | self.QUERY_LIMITED, False, self.pid)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), f'OpenProcess({pid}) failed')

    @classmethod
    def maybe(cls, pid, created) -> 'Proc | None':
        """The live process with this id and creation time, else None (exited or id reused)."""
        try:
            proc = cls(pid)
        except (OSError, TypeError, ValueError):
            return None
        if proc.alive() and proc.created() == created:
            return proc
        proc.close()
        return None

    def created(self) -> int:
        from ctypes import wintypes
        times = [wintypes.FILETIME() for _ in range(4)]
        if not self._k.GetProcessTimes(self.handle, *[self._ct.byref(t) for t in times]):
            raise OSError(self._ct.get_last_error(), 'GetProcessTimes failed')
        return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime

    def image(self) -> str:
        from ctypes import wintypes
        size = wintypes.DWORD(32768)
        buf = self._ct.create_unicode_buffer(size.value)
        if not self._k.QueryFullProcessImageNameW(self.handle, 0, buf, self._ct.byref(size)):
            raise OSError(self._ct.get_last_error(), 'QueryFullProcessImageNameW failed')
        return buf.value

    def alive(self) -> bool:
        from ctypes import wintypes
        code = wintypes.DWORD()
        self._k.GetExitCodeProcess(self.handle, self._ct.byref(code))
        return code.value == self.STILL_ACTIVE

    def wait(self, seconds: float) -> bool:
        """Wait on the process handle itself (its own completion signal); True once it has exited."""
        return self._k.WaitForSingleObject(self.handle, int(seconds * 1000)) == 0

    def in_any_job(self) -> bool:
        from ctypes import wintypes
        result = wintypes.BOOL()
        if not self._k.IsProcessInJob(self.handle, None, self._ct.byref(result)):
            raise OSError(self._ct.get_last_error(), 'IsProcessInJob failed')
        return bool(result.value)

    def terminate(self) -> None:
        if not self._k.TerminateProcess(self.handle, 1):
            raise OSError(self._ct.get_last_error(), 'TerminateProcess failed')

    def close(self) -> None:
        if self.handle:
            self._k.CloseHandle(self.handle)
            self.handle = None


JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOB_OBJECT_LIMIT_BREAKAWAY_OK = 0x0800
JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK = 0x1000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9


def _job_structs():
    import ctypes
    from ctypes import wintypes

    class Basic(ctypes.Structure):
        _fields_ = [('PerProcessUserTimeLimit', ctypes.c_int64), ('PerJobUserTimeLimit', ctypes.c_int64),
                    ('LimitFlags', wintypes.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                    ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', wintypes.DWORD),
                    ('Affinity', ctypes.c_size_t), ('PriorityClass', wintypes.DWORD),
                    ('SchedulingClass', wintypes.DWORD)]

    class IoCounters(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint64) for n in ('ReadOps', 'WriteOps', 'OtherOps', 'ReadBytes', 'WriteBytes',
                                                   'OtherBytes')]

    class Extended(ctypes.Structure):
        _fields_ = [('BasicLimitInformation', Basic), ('IoInfo', IoCounters),
                    ('ProcessMemoryLimit', ctypes.c_size_t), ('JobMemoryLimit', ctypes.c_size_t),
                    ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]
    return Extended


class KillOnCloseJob:
    """A Job Object whose last handle closing ends every process in it. Its handle is not inheritable
    and is held by its creator only, so the job lives exactly as long as that process."""

    def __init__(self):
        import ctypes
        self._ct, self._k = ctypes, _k32()
        self.handle = self._k.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), 'CreateJobObjectW failed')
        info = _job_structs()()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self._k.SetInformationJobObject(self.handle, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
                                               ctypes.byref(info), ctypes.sizeof(info)):
            raise OSError(ctypes.get_last_error(), 'SetInformationJobObject failed')

    def limit_flags(self) -> int:
        info = _job_structs()()
        if not self._k.QueryInformationJobObject(self.handle, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
                                                 self._ct.byref(info), self._ct.sizeof(info), None):
            raise OSError(self._ct.get_last_error(), 'QueryInformationJobObject failed')
        return int(info.BasicLimitInformation.LimitFlags)

    def assign_current(self) -> None:
        if not self._k.AssignProcessToJobObject(self.handle, self._k.GetCurrentProcess()):
            raise OSError(self._ct.get_last_error(), 'AssignProcessToJobObject(current) failed')

    def contains(self, process_handle) -> bool:
        from ctypes import wintypes
        result = wintypes.BOOL()
        if not self._k.IsProcessInJob(process_handle, self.handle, self._ct.byref(result)):
            raise OSError(self._ct.get_last_error(), 'IsProcessInJob failed')
        return bool(result.value)


class JobSupervision:
    """The supervisor's side of the managed environment: it joins a new kill-on-close job, so every
    process it starts from now on is born inside the job, and checks that the job ends them all."""

    def __init__(self, job_factory=KillOnCloseJob):
        try:
            self.job = job_factory()
            self.job.assign_current()
            self.flags = self.job.limit_flags()
        except OSError as exc:
            raise LifecycleError('SUPERVISION_UNAVAILABLE', f'the kill-on-close Job Object: {exc}',
                                 refusal=False) from None
        if not self.flags & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE or self.flags & (JOB_OBJECT_LIMIT_BREAKAWAY_OK |
                                                                             JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK):
            raise LifecycleError('JOB_UNSAFE', f'job limit flags {self.flags:#x}', refusal=False)

    def report(self) -> dict:
        return {'limit_flags': hex(self.flags), 'kill_on_job_close': True, 'breakaway_allowed': False}

    def contains(self, process_handle) -> bool:
        return self.job.contains(process_handle)


# ---------------------------------------------------------------- sockets and tokens


def _ip4(value: int) -> str:
    return socket.inet_ntoa(struct.pack('<I', value))


def _port(value: int) -> int:
    return socket.ntohs(value & 0xFFFF)


def sockets(pid: int | None = None) -> list[dict]:
    """TCP listeners and UDP endpoints, IPv4 and IPv6, from GetExtendedTcpTable/GetExtendedUdpTable;
    filtered to one owning process when pid is given."""
    import ctypes
    from ctypes import wintypes
    ip = ctypes.WinDLL('iphlpapi')
    rows = []
    tables = (('tcp', socket.AF_INET, 3, 24), ('tcp', socket.AF_INET6, 3, 56),   # TCP_TABLE_OWNER_PID_LISTENER
              ('udp', socket.AF_INET, 1, 12), ('udp', socket.AF_INET6, 1, 28))   # UDP_TABLE_OWNER_PID
    for proto, family, table_class, row_size in tables:
        func = ip.GetExtendedTcpTable if proto == 'tcp' else ip.GetExtendedUdpTable
        size = wintypes.DWORD(0)
        func(None, ctypes.byref(size), False, family, table_class, 0)
        for _ in range(4):
            buf = ctypes.create_string_buffer(size.value + 4096)
            size = wintypes.DWORD(len(buf))
            code = func(buf, ctypes.byref(size), False, family, table_class, 0)
            if code == 0:
                break
            if code != 122:  # ERROR_INSUFFICIENT_BUFFER: the table grew; retry
                raise OSError(code, f'GetExtended{proto.title()}Table failed')
        data = buf.raw
        count = struct.unpack_from('<I', data, 0)[0]
        for i in range(count):
            off = 4 + i * row_size
            if family == socket.AF_INET:
                if proto == 'tcp':
                    _state, laddr, lport, _r, _rp, owner = struct.unpack_from('<6I', data, off)
                else:
                    laddr, lport, owner = struct.unpack_from('<3I', data, off)
                address = _ip4(laddr)
            else:
                address = socket.inet_ntop(socket.AF_INET6, data[off:off + 16])
                if proto == 'tcp':
                    _scope, lport = struct.unpack_from('<2I', data, off + 16)
                    owner = struct.unpack_from('<I', data, off + 52)[0]
                else:
                    _scope, lport, owner = struct.unpack_from('<3I', data, off + 16)
            if pid is None or owner == pid:
                rows.append({'proto': proto, 'family': 'ipv4' if family == socket.AF_INET else 'ipv6',
                             'address': address, 'port': _port(lport), 'pid': owner})
    return rows


def token_report(pid: int) -> dict:
    """The process token's elevation (TokenElevation, TokenElevationType) and integrity level RID."""
    import ctypes
    from ctypes import wintypes
    k, adv = _k32(), ctypes.WinDLL('advapi32', use_last_error=True)
    adv.OpenProcessToken.argtypes = (wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE))
    adv.GetTokenInformation.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
                                        ctypes.POINTER(wintypes.DWORD))
    adv.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
    adv.GetSidSubAuthorityCount.argtypes = (wintypes.LPVOID,)
    adv.GetSidSubAuthority.restype = ctypes.POINTER(wintypes.DWORD)
    adv.GetSidSubAuthority.argtypes = (wintypes.LPVOID, wintypes.DWORD)
    process = k.OpenProcess(Proc.QUERY_LIMITED, False, pid)
    if not process:
        raise OSError(ctypes.get_last_error(), f'OpenProcess({pid}) failed')
    token = wintypes.HANDLE()
    try:
        if not adv.OpenProcessToken(process, 0x0008, ctypes.byref(token)):  # TOKEN_QUERY
            raise OSError(ctypes.get_last_error(), 'OpenProcessToken failed')

        def info(cls: int, size: int):
            buf, needed = ctypes.create_string_buffer(size), wintypes.DWORD()
            if not adv.GetTokenInformation(token, cls, buf, size, ctypes.byref(needed)):
                raise OSError(ctypes.get_last_error(), f'GetTokenInformation({cls}) failed')
            return buf
        elevated = struct.unpack('<I', info(20, 4).raw[:4])[0]          # TokenElevation
        elevation_type = struct.unpack('<I', info(18, 4).raw[:4])[0]    # TokenElevationType
        label = info(25, 256)                                           # TokenIntegrityLevel
        sid = ctypes.cast(label, ctypes.POINTER(ctypes.c_void_p))[0]
        rid = adv.GetSidSubAuthority(sid, adv.GetSidSubAuthorityCount(sid)[0] - 1)[0]
    finally:
        if token:
            k.CloseHandle(token)
        k.CloseHandle(process)
    return {'elevated': bool(elevated), 'elevation_type': {1: 'default', 2: 'full', 3: 'limited'}.get(elevation_type,
            str(elevation_type)), 'integrity_rid': hex(rid)}


def port_in_use(port: int, address: str = '127.0.0.1') -> bool:
    """The port is in use when any TCP row of the table holds it (on any address), or when binding it on
    address exclusively fails."""
    if any(row['port'] == port and row['proto'] == 'tcp' for row in sockets()):
        return True
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.setsockopt(socket.SOL_SOCKET, getattr(socket, 'SO_EXCLUSIVEADDRUSE', socket.SO_REUSEADDR), 1)
        probe.bind((address, port))
        return False
    except OSError:
        return True
    finally:
        probe.close()


# ---------------------------------------------------------------- verified bytes


@contextlib.contextmanager
def locked_read(path: Path):
    """A read handle that shares read only: no writer, rename or delete while it is held."""
    import ctypes
    import msvcrt
    from ctypes import wintypes
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    generic_read, file_share_read, open_existing = 0x80000000, 0x1, 3
    handle = k32.CreateFileW(str(path), generic_read, file_share_read, None, open_existing, 0, None)
    if handle in (None, wintypes.HANDLE(-1).value):
        raise LifecycleError('BINARY_UNREADABLE', f'{path}: CreateFileW failed ({ctypes.get_last_error()})')
    with os.fdopen(msvcrt.open_osfhandle(handle, os.O_RDONLY), 'rb') as stream:
        yield stream


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


class WindowsCredentialProvider(contract.CredentialProvider):
    """Windows Credential Manager generic credentials (CredentialStore); the secret is stored as UTF-16LE, as
    the Credential Manager UI shows it."""

    def __init__(self, store=None):
        self.store = store or CredentialStore()

    def get(self, name):
        entry = self.store.read(name)
        return None if entry is None else (entry[0], entry[1].decode('utf-16-le'))

    def set(self, name, user, secret, comment=''):
        self.store.write(name, user, secret.encode('utf-16-le'), comment)

    def delete(self, name):
        return self.store.delete(name)


# ---------------------------------------------------------------- the adapter


class WindowsAdapter(contract.PlatformAdapter):
    system = 'Windows'
    verified_bytes = 'started-bytes: hashed through a read-only-shared handle held while the process starts'
    supervision = {
        'mechanism': 'job-object',
        'detail': 'the supervisor joins a new Job Object with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE before it starts '
                  'the service and holds its only handle; breakaway is not allowed',
        'ends_on': ['explicit stop (down)', 'the supervisor exiting or being killed (the kernel closes the job)',
                    "the end of the user's session, which ends the supervisor"],
        'limit': 'a process outside the job is not covered; the job does not survive the supervisor',
    }
    credentials = {'provider': 'windows-credential-manager',
                   'mechanism': 'generic credentials through CredWriteW, CredReadW and CredDeleteW (advapi32), '
                                'persisted per local machine for the user'}

    def __init__(self, machine: str = 'AMD64'):
        self.machine = machine
        self.asset_key = contract.asset_key(self.system, machine)

    def launch_supervisor(self, argv, log, cwd):
        """Detached, in a new process group, and broken away from the caller's job where the caller's job
        allows it (a caller whose job forbids breakaway gets a supervisor that also ends with it)."""
        base = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            return subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=log, stderr=log, close_fds=True,
                                    cwd=str(cwd), creationflags=base | subprocess.CREATE_BREAKAWAY_FROM_JOB)
        except OSError:  # the caller's job forbids breakaway: the supervisor then also ends with the caller
            return subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=log, stderr=log, close_fds=True,
                                    cwd=str(cwd), creationflags=base)

    def enter_supervision(self):
        return JobSupervision()

    def process(self, pid):
        return Proc(pid)

    def process_maybe(self, pid, created):
        return Proc.maybe(pid, created)

    def listeners(self, pid=None):
        return sockets(pid)

    def port_in_use(self, port, address='127.0.0.1'):
        return port_in_use(port, address)

    def user_identity(self, pid):
        return token_report(pid)

    def locked_read(self, path):
        return locked_read(path)

    def credential_provider(self):
        return WindowsCredentialProvider()
