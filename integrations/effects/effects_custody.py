"""Custody-template verification for the effects store (decision 0004, point 2).

Read-only: this module reads the owner and the DACL that the operating system
actually holds for a path and compares them with the custody template. It never
changes a permission. Creating and permissioning the effects root is an Owner act
(A4, from an elevated window), never something this code does.

Windows template (the root directory):

* the DACL is protected (inheritance disabled) and holds no inherited ACE;
* the owner is SYSTEM, BUILTIN\\Administrators or the configured principal;
* every ACE's SID is SYSTEM (S-1-5-18), BUILTIN\\Administrators (S-1-5-32-544)
  or the configured principal; any other SID (Users, Authenticated Users,
  Everyone, the Owner's interactive account, OWNER RIGHTS, ...) is refused;
* every ACE is a plain allow or deny ACE (no object or callback ACEs).

Files and directories inside the root (the database, its -wal and -shm, the
backups) inherit from the protected root, so inherited ACEs are expected there;
their owner and every ACE SID must still be in the template.

POSIX template: the root directory is mode 0700, files are 0600, and the owner
uid is the configured principal (root, uid 0, when none is configured).

Each violation has a name; a refusal lists every violation found.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat
import sys

SYSTEM_SID = 'S-1-5-18'
ADMINISTRATORS_SID = 'S-1-5-32-544'
WELL_KNOWN = {SYSTEM_SID: 'NT AUTHORITY\\SYSTEM', ADMINISTRATORS_SID: 'BUILTIN\\Administrators',
              'S-1-5-32-545': 'BUILTIN\\Users', 'S-1-5-11': 'Authenticated Users', 'S-1-1-0': 'Everyone',
              'S-1-3-4': 'OWNER RIGHTS', 'S-1-3-0': 'CREATOR OWNER', 'S-1-5-4': 'INTERACTIVE'}

INHERITED_ACE = 0x10
INHERIT_ONLY_ACE = 0x08
SE_DACL_PROTECTED = 0x1000
ACCESS_ALLOWED_ACE_TYPE = 0
ACCESS_DENIED_ACE_TYPE = 1

# Violation names.
NULL_DACL = 'CUSTODY_NULL_DACL'
INHERITANCE_ENABLED = 'CUSTODY_INHERITANCE_ENABLED'
INHERITED_ACE_FOUND = 'CUSTODY_INHERITED_ACE'
EXTRA_ACE = 'CUSTODY_EXTRA_ACE'
UNSUPPORTED_ACE = 'CUSTODY_UNSUPPORTED_ACE_TYPE'
WRONG_OWNER = 'CUSTODY_WRONG_OWNER'
WRONG_MODE = 'CUSTODY_WRONG_MODE'
UNREADABLE = 'CUSTODY_UNREADABLE'


class CustodyRefused(Exception):
    """The path does not meet the custody template. ``violations`` lists (name, detail)."""

    def __init__(self, path: Path, violations: list[tuple[str, str]]):
        self.path = Path(path)
        self.violations = list(violations)
        self.codes = [code for code, _ in violations]
        lines = '; '.join(f'{code}: {detail}' for code, detail in violations)
        super().__init__(f'custody template not met for {path}: {lines}')


@dataclass(frozen=True)
class Ace:
    ace_type: int
    flags: int
    mask: int
    sid: str

    @property
    def inherited(self) -> bool:
        return bool(self.flags & INHERITED_ACE)


@dataclass(frozen=True)
class SecurityInfo:
    owner_sid: str
    dacl_present: bool
    dacl_protected: bool
    aces: tuple[Ace, ...]


@dataclass(frozen=True)
class CustodyTemplate:
    """The custody template: SYSTEM, Administrators and an optional configured principal.

    ``principal`` is a SID string on Windows (the executor principal from G-04.2.1;
    in fixtures, the test process's own SID) or a uid on POSIX. None is the interim
    template of decision 0004: SYSTEM and Administrators only.
    """
    principal: str | int | None = None

    def allowed_sids(self) -> frozenset[str]:
        sids = {SYSTEM_SID, ADMINISTRATORS_SID}
        if isinstance(self.principal, str):
            sids.add(self.principal)
        return frozenset(sids)

    def describe(self) -> dict:
        if sys.platform == 'win32':
            return {'platform': 'windows', 'allowed_sids': sorted(self.allowed_sids()),
                    'owner_in': sorted(self.allowed_sids()), 'root_dacl_protected': True,
                    'inherited_aces_on_root': False}
        return {'platform': 'posix', 'owner_uid': 0 if self.principal is None else self.principal,
                'root_mode': '0700', 'file_mode': '0600'}


def _name(sid: str) -> str:
    return f'{sid} ({WELL_KNOWN[sid]})' if sid in WELL_KNOWN else sid


def evaluate_windows(info: SecurityInfo, template: CustodyTemplate, *, is_root: bool) -> list[tuple[str, str]]:
    """Pure comparison of read-back security information with the template."""
    allowed = template.allowed_sids()
    violations = []
    if info.owner_sid not in allowed:
        violations.append((WRONG_OWNER, f'owner {_name(info.owner_sid)} is not one of '
                                        f'{sorted(allowed)}'))
    if not info.dacl_present:
        violations.append((NULL_DACL, 'no DACL: everyone has full access'))
        return violations
    if is_root and not info.dacl_protected:
        violations.append((INHERITANCE_ENABLED, 'the root DACL is not protected: inheritance is enabled'))
    for ace in info.aces:
        if ace.ace_type not in (ACCESS_ALLOWED_ACE_TYPE, ACCESS_DENIED_ACE_TYPE):
            violations.append((UNSUPPORTED_ACE, f'ACE type {ace.ace_type} for {_name(ace.sid)}'))
        if is_root and ace.inherited:
            violations.append((INHERITED_ACE_FOUND, f'inherited ACE for {_name(ace.sid)} '
                                                    f'(flags {ace.flags:#04x}, mask {ace.mask:#010x})'))
        if ace.sid not in allowed:
            violations.append((EXTRA_ACE, f'ACE for {_name(ace.sid)} (type {ace.ace_type}, flags '
                                          f'{ace.flags:#04x}, mask {ace.mask:#010x}) is not in the template'))
    return violations


def evaluate_posix(mode: int, uid: int, template: CustodyTemplate, *, is_dir: bool) -> list[tuple[str, str]]:
    """Pure comparison of a POSIX mode and owner with the template."""
    expected_uid = 0 if template.principal is None else int(template.principal)
    want = 0o700 if is_dir else 0o600
    violations = []
    if uid != expected_uid:
        violations.append((WRONG_OWNER, f'owner uid {uid} is not {expected_uid}'))
    if stat.S_IMODE(mode) != want:
        violations.append((WRONG_MODE, f'mode {stat.S_IMODE(mode):04o} is not {want:04o}'))
    return violations


def check_path(path: Path, template: CustodyTemplate, *, is_root: bool) -> None:
    """Read back the path's owner and permissions and refuse unless they meet the template."""
    path = Path(path)
    if sys.platform == 'win32':
        try:
            info = read_security(path)
        except OSError as exc:
            raise CustodyRefused(path, [(UNREADABLE, f'cannot read the security descriptor: {exc}')]) from None
        violations = evaluate_windows(info, template, is_root=is_root)
    else:
        st = os.lstat(path)
        if stat.S_ISLNK(st.st_mode):
            raise CustodyRefused(path, [(UNREADABLE, 'a symbolic link is not accepted')])
        violations = evaluate_posix(st.st_mode, st.st_uid, template, is_dir=stat.S_ISDIR(st.st_mode))
    if violations:
        raise CustodyRefused(path, violations)


# ---------------------------------------------------------------------------
# Windows security API (read-only)

def _advapi():
    import ctypes
    from ctypes import wintypes
    advapi = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    advapi.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p)]
    advapi.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    advapi.ConvertSidToStringSidW.restype = wintypes.BOOL
    advapi.GetSecurityDescriptorControl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.WORD),
                                                    ctypes.POINTER(wintypes.DWORD)]
    advapi.GetSecurityDescriptorControl.restype = wintypes.BOOL
    advapi.GetAce.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    advapi.GetAce.restype = wintypes.BOOL
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi.OpenProcessToken.restype = wintypes.BOOL
    advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                           ctypes.POINTER(wintypes.DWORD)]
    advapi.GetTokenInformation.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    return ctypes, wintypes, advapi, kernel


def _sid_string(ctypes, wintypes, advapi, kernel, sid_pointer) -> str:
    text = wintypes.LPWSTR()
    if not advapi.ConvertSidToStringSidW(sid_pointer, ctypes.byref(text)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return text.value
    finally:
        kernel.LocalFree(text)


def read_security(path: Path) -> SecurityInfo:
    """GetNamedSecurityInfoW(OWNER | DACL): the owner, the DACL control bits and every ACE."""
    ctypes, wintypes, advapi, kernel = _advapi()
    se_file_object, owner_info, dacl_info = 1, 0x1, 0x4

    class ACL(ctypes.Structure):
        _fields_ = [('AclRevision', ctypes.c_ubyte), ('Sbz1', ctypes.c_ubyte), ('AclSize', wintypes.WORD),
                    ('AceCount', wintypes.WORD), ('Sbz2', wintypes.WORD)]

    owner, dacl, descriptor = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
    rc = advapi.GetNamedSecurityInfoW(str(path), se_file_object, owner_info | dacl_info, ctypes.byref(owner),
                                      None, ctypes.byref(dacl), None, ctypes.byref(descriptor))
    if rc:
        raise OSError(rc, ctypes.FormatError(rc), str(path))
    try:
        control, revision = wintypes.WORD(), wintypes.DWORD()
        if not advapi.GetSecurityDescriptorControl(descriptor, ctypes.byref(control), ctypes.byref(revision)):
            raise ctypes.WinError(ctypes.get_last_error())
        aces = []
        if dacl.value:
            acl = ACL.from_address(dacl.value)
            for index in range(acl.AceCount):
                ace = ctypes.c_void_p()
                if not advapi.GetAce(dacl, index, ctypes.byref(ace)):
                    raise ctypes.WinError(ctypes.get_last_error())
                ace_type = ctypes.c_ubyte.from_address(ace.value).value
                flags = ctypes.c_ubyte.from_address(ace.value + 1).value
                mask = wintypes.DWORD.from_address(ace.value + 4).value
                if ace_type in (ACCESS_ALLOWED_ACE_TYPE, ACCESS_DENIED_ACE_TYPE):
                    sid = _sid_string(ctypes, wintypes, advapi, kernel, ace.value + 8)
                else:
                    sid = f'<ace type {ace_type}>'
                aces.append(Ace(ace_type, flags, mask, sid))
        return SecurityInfo(owner_sid=_sid_string(ctypes, wintypes, advapi, kernel, owner),
                            dacl_present=bool(dacl.value),
                            dacl_protected=bool(control.value & SE_DACL_PROTECTED),
                            aces=tuple(aces))
    finally:
        kernel.LocalFree(descriptor)


def current_user_sid() -> str:
    """The SID of this process's token user (Windows only); used by the tests."""
    ctypes, wintypes, advapi, kernel = _advapi()
    token_query, token_user = 0x0008, 1
    token = wintypes.HANDLE()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), token_query, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        size = wintypes.DWORD()
        advapi.GetTokenInformation(token, token_user, None, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi.GetTokenInformation(token, token_user, buffer, size, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        sid_pointer = ctypes.c_void_p.from_buffer(buffer).value  # TOKEN_USER.User.Sid
        return _sid_string(ctypes, wintypes, advapi, kernel, sid_pointer)
    finally:
        kernel.CloseHandle(token)
