# Credential provider (`integrations/credentials/`)

Plan leaf F-06.3, blueprint section
[`#infrastructure-state`](../../AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html#infrastructure-state),
the accepted cross-platform lifecycle design (Architect gates C, F and G, accepted by the Overseer on
2026-11-07) and draft decision 0011 section 3 (accepted at the completion of F-06.2 and F-06.3); decision
[0007](../../decisions/0007-role-token-matrix-and-revocation-contract.md) point 5 for the receipts. Windows
record: [`evidence/F-06.3-credential-provider.md`](../../evidence/F-06.3-credential-provider.md).

Where the harness keeps service credentials, by entry name: `get`, `set`, `delete`, `exists`. The interface
is the lifecycle contract's `CredentialProvider`
([`integrations/platform/platform_contract.py`](../platform/README.md)), published here under the same
name. The platform adapter supplies the provider through this module's factory, and
[`gitea_host.py` and `gitea_roles.py`](../gitea/README.md) reach it that way.

## Files

| Path | What |
|---|---|
| `credential_provider.py` | `CredentialStore` and `WindowsCredentialProvider` (Credential Manager through standard-library ctypes, moved from `integrations/platform/platform_windows.py`), the Windows credential field limits (`CREDENTIAL_LIMITS`, `check_credential_fields`), `KeyringProvider` and `qualify_keyring`, the factory `select_provider`, `doctor` and its command line, and `ActReceipt`, the integration-store receipt of a credential act |
| `tests/test_credential_provider.py` | The provider contract suite over a fake, the Windows provider (its real ctypes code over an in-memory advapi32; Windows) and `KeyringProvider` with an in-process keyring backend; the Windows field limits over the fake and the Windows provider; the factory and its refusals; keyring's own selection and configuration shown ignored; the module's reachable names read from its syntax tree; `doctor` |
| `tests/test_receipts.py` | `ActReceipt` on a fixture integration store; `gitea_roles.py rotate` and `retire` end to end over the fake Gitea, writing their receipts into the fixture store |
| `tests/test_crossread.py`, `tests/crossread_support.py` | The throwaway-name cross-read: written in this process, read back by name in a separate process, deleted, checked absent in a separate process, then the I7 scan of what the processes printed. Default mode: a keyring backend of the test that keeps its entries in a temporary JSON file. Real-store mode: opt-in (below) |

## The providers and the factory

| System | Provider | How it is chosen and qualified |
|---|---|---|
| Windows | `windows-credential-manager`: generic credentials through `CredWriteW`, `CredReadW`, `CredDeleteW` (advapi32), persisted per local machine for the user, secrets as UTF-16LE | `advapi32` loads. keyring is never imported by the factory on Windows and no keyring backend is instantiated there (`WinVaultKeyring` included), although the tools set installs keyring on every platform |
| Linux | `keyring-secret-service`: keyring 25.7.0 `SecretService.Keyring()` | instantiated explicitly; qualified when its `.priority` is a number above zero and it can find an entry by its name alone |
| macOS | `keyring-macos-keychain`: keyring 25.7.0 `macOS.Keyring()` | the same qualification |
| anything else | none | `NO_CREDENTIAL_PROVIDER` |

`select_provider()` is the factory: the harness chooses the provider from the running system
(`platform.system()`), never from configuration or the environment (I6), and fails closed (I5): with no
qualified provider it refuses `NO_CREDENTIAL_PROVIDER` with its remedy, and there is never a file or
plaintext fallback. The refusals:

- an unknown system;
- Credential Manager not loadable;
- keyring not importable (the POSIX lifecycle runs under the tools venv: `task tools:install`);
- a keyring backend whose `.priority` raises (keyring's way of saying "not viable here") or is not a number
  above zero;
- a keyring backend that cannot find an entry by its name alone: keyring's default `get_credential` needs
  the user name, and one named entry per credential (I2) could not then be read back.

What keyring offers for choosing or configuring a backend is never used: `keyring.get_keyring()` or
anything of `keyring.core`, a `keyringrc`, `PYTHON_KEYRING_BACKEND`, the keyring command line,
`keyrings.alt` and plug-in entry points. `KeyringBackend.__init__` copies `KEYRING_PROPERTY_*` environment
variables onto the instance; the factory removes them from it, and clears the macOS backend's
`keychain` (taken from `KEYCHAIN_PATH` at import), and `doctor` names what it ignored.

## Windows credential field limits

`CREDENTIAL_LIMITS` is the one statement of the limits of a generic credential's fields that the harness
relies on, as `wincred.h` defines them and the `CREDENTIALW` structure's documentation applies them:

| Field | Limit | Source (`wincred.h`) |
|---|---|---|
| `TargetName` | 32767 characters | `CRED_MAX_GENERIC_TARGET_NAME_LENGTH` |
| `UserName` | 513 characters | `CRED_MAX_USERNAME_LENGTH` (256+1+256) |
| `Comment` | 256 characters | `CRED_MAX_STRING_LENGTH` |
| `CredentialBlob` | 2560 bytes | `CRED_MAX_CREDENTIAL_BLOB_SIZE` (5*512) |

Characters are UTF-16 code units, without the terminating NUL; the blob is the secret as the Windows
provider stores it, UTF-16LE (`secret_blob_size`). `CredentialStore.write` checks every field before it
calls `CredWriteW` and refuses `CREDENTIAL_FIELD_LIMIT`, naming each field over its limit, with nothing
written; `CredWriteW` itself rejects such a field with an error of its own (an over-long comment failed
with 1734 on 2026-11-11). A caller checks an entry it has yet to write with `check_credential_fields`
(`credential_field_problems` lists the problems), which reads and writes no entry; `gitea_roles.py` does
so before it mints a token. A check that passes is no guarantee that the write succeeds: `CredWriteW`'s
own failure is still `CREDENTIAL_WRITE_FAILED` with its code. The tests' fake providers enforce the same
limits with the same error. The keyring providers do not apply them.

`KeyringProvider` keeps one entry per name: keyring's service is the entry name, its user name the
credential's user and its password the secret. keyring has no comment field, so a comment is not stored.
Replacing an entry under another user stores the new one first (I3) and deletes the old one after (I2).
keyring errors are reported by their type only: `KeyringLocked` and `InitError` are
`CREDENTIAL_PROVIDER_LOCKED`; any other is `CREDENTIAL_READ_FAILED`, `CREDENTIAL_WRITE_FAILED` or
`CREDENTIAL_DELETE_FAILED`.

## Receipts of credential acts

Every rotate or retire act writes an integration-store receipt (`ActReceipt`, format
`aieh-credential-act/1`) through the store's own receipts
([`integrations/store/`](../store/README.md)): the intent holds the verb, the service, the entry, the user,
the role, the fingerprint before, the provider, the trigger, the revoker and the affected attempts
(decision 0007 point 5). It is reserved before anything changes (without it the act does not start),
dispatched before the upstream change, then confirmed with the outcome's fingerprints, failed (the harness
observed that the change did not apply) or unknown (the outcome is uncertain; reconciliation required),
and read back: an act whose receipt is not read back as written fails with `CREDENTIAL_RECEIPT_UNREAD`.
Fingerprints only (I8); the act's exposure guard scans what the receipt holds (I7).

The Gitea credential acts write into `persistent/state/integration/integration.sqlite` of the managed root,
the integration store's location under [decision 0009](../../decisions/0009-managed-data-root-and-configuration-contract.md)
(its move from the legacy per-user location is F-07.2). A caller that passes its own context passes its
own store, so a fixture act never reaches the managed one.

## Commands

```
<tools python> -I -B -m unittest discover -s integrations/credentials/tests -v   # task credentials:test
<tools python> -I -B integrations/credentials/credential_provider.py doctor        # task credentials:doctor
```

`doctor` reports the chosen provider, its mechanism and viability (for keyring, the backend and its
priority, and what it ignored), or the refusal with its remedy. It reads, writes and lists no entry and
prints no secret, and its output passes the I7 scan. Exit 0 viable, 2 refused.

### The real-store cross-read (opt-in)

```
AIEH_CREDENTIALS_REAL_STORE=1 <tools python> -I -B -m unittest discover -s integrations/credentials/tests -p test_crossread.py -v
```

On Windows only, with `AIEH_CREDENTIALS_REAL_STORE=1`, `TestCrossReadRealStore` runs the cross-read
against the provider the factory chooses, the real Credential Manager, with one throwaway entry: the name
`AIEH test cross-read ` followed by 32 random hex digits, the user `aieh-test-cross-read` and a random,
non-secret value. It reads that name once to see that it is absent, writes it, has a child process read it
by name (the child prints the user and the value's fingerprint, never the value), deletes it, has a child
process check that it is gone, and deletes it again in cleanup if a step failed. It reads, writes and
deletes no other entry and never enumerates the store. Without the variable it skips with its reason.

## Not yet verified

- keyring's Secret Service and Keychain backends on a real host (F-06.4, F-06.5), and the Linux and macOS
  installations of the keyring closure.
- macOS: keyring 25.7.0's `macOS.Keyring` inherits the default `get_credential`, which needs the user
  name, so the factory refuses it (`NO_CREDENTIAL_PROVIDER`) as it stands; F-06.5 decides how an entry is
  found by its name on macOS.
- The real-store cross-read on Windows (opt-in; it needs the Owner's approval to run).
- `CREDENTIAL_PROVIDER_LOCKED` in a real session without a credential store (fakes only).
- The field limits against the real Credential Manager at their exact boundaries (a 256-character comment
  accepted, 257 refused): they are checked over the in-memory advapi32 only; the real store has been seen to
  accept a 232-character comment and to refuse a 271-character one.
- The receipts against the running Gitea and the managed root's integration store (fakes and a fixture
  store only).
