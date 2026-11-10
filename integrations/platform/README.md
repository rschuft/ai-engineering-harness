# Host-service lifecycle contract and platform adapters (`integrations/platform/`)

Plan leaf F-06.2, blueprint section
[`#infrastructure-state`](../../AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html#infrastructure-state),
the accepted cross-platform lifecycle design (Architect gates C, F and G, accepted by the Overseer on
2026-11-07) and draft decision 0011 (accepted at the completion of F-06.2 and F-06.3). Windows record:
[`evidence/F-06.2-platform-windows.md`](../../evidence/F-06.2-platform-windows.md).

A host service of the harness (today Gitea: [`integrations/gitea/gitea_host.py`](../gitea/README.md))
is driven through one contract on every platform. The contract is platform-neutral Python, standard
library only. A platform adapter supplies only what differs per operating system. Linux and macOS
adapters follow in F-06.4 and F-06.5; until then the contract refuses them with
`PLATFORM_UNSUPPORTED`.

## Files

| Path | What |
|---|---|
| `platform_contract.py` | The verbs, the records, the refusal codes and their remedies, adapter selection, the `CredentialProvider` interface, the write-ahead transition log and the transition verbs over a service's operations, and the I7 exposure guard |
| `platform_windows.py` | The Windows adapter, extracted unchanged from F-06.1's `gitea_host.py`: the kill-on-close Job Object, process identity, the TCP and UDP tables, the process token, the read-only-shared binary handle, Credential Manager |
| `tests/test_platform_contract.py` | The contract: verbs, formats, codes and remedies, asset keys, adapter selection, run and readiness records, versions, transitions and their orchestration over a fake service, the exposure guard (offline) |
| `tests/test_platform_windows.py` | The Windows adapter's declarations and refusals with fakes; its listener, token and identity reads of the test process (Windows) |

## Verbs

| Group | Verbs |
|---|---|
| service | `install`, `up`, `down`, `restart`, `status`, `inspect`, `verify` |
| credentials | `provision`, `rotate`, `retire` |
| transitions | `upgrade`, `recover`, `uninstall` |

How Gitea realizes each one is in [its README](../gitea/README.md#the-lifecycle-contracts-verbs).
`restart`, `upgrade`, `recover` and `uninstall` are orchestrated here (`restart`, `upgrade`, `recover`,
`uninstall` over `ServiceOperations`); the service supplies observe, stop, start, ready, stage, backup,
restore, set-desired, the pinned versions, and the removal of ephemeral state.

## Records

| Format | What |
|---|---|
| `aieh-platform/1` | `system`, `machine`, `asset_key` (for example `windows-amd64`), `supervision` (mechanism, what ends the managed environment, its limit), `credentials` (provider and mechanism) |
| `aieh-asset/1` | the managed root's asset record ([decision 0009](../../decisions/0009-managed-data-root-and-configuration-contract.md)) |
| `aieh-gitea-host/1` | Gitea's host record, with an optional `platform.asset_key` (absent in a record written before F-06.2; another platform's key is `PLATFORM_MISMATCH`) |
| `aieh-service-run/1` | the managed environment's run record; it generalises `aieh-gitea-run/1`, which readers still accept |
| `aieh-readiness/1` | a service's readiness checks under platform-neutral names (a name holding a mechanism word such as `job`, `token`, `pid`, `windows` is refused), with the `aieh-platform/1` record of the platform they ran on |
| `aieh-service-transition/1` | one write-ahead record per transition (`restart`, `upgrade`, `uninstall`): `pending` before any process is replaced, then each step, then `completed`, `rolled-back` or `failed`; desired, staged, running and target versions kept distinct. At most one is pending |

## Refusal codes

A component keeps its existing codes unchanged. The contract adds these, each carrying its remedy in
its message (`CODE: detail (remedy: ...)`):

| Code | When |
|---|---|
| `PLATFORM_UNSUPPORTED` | no adapter for this system (Linux and macOS until F-06.4 and F-06.5) |
| `PLATFORM_MISMATCH` | a record names another platform's asset key |
| `SUPERVISION_UNAVAILABLE` | the supervision mechanism cannot be set up (Windows: the Job Object cannot be created or joined) |
| `NO_CREDENTIAL_PROVIDER` | no qualified credential provider; there is never a file or plaintext fallback |
| `CREDENTIAL_PROVIDER_LOCKED` | the provider is not available to this session (Windows: no logon session credentials) |
| `VERSION_MISMATCH` | a target without a pin, a version that is not a release version, or a running version that is not the desired one |
| `DOWNGRADE_REFUSED` | a target lower than the desired version: a downgrade is an Owner decision, never automatic |
| `TRANSITION_PENDING` | another transition is pending: run `recover` |
| `UNINSTALL_RUNNING` | `uninstall` while the service runs: run `down` first |

## Credential invariants

I1-I8 bind every act: a secret is never printed, logged, on a command line or in an environment
variable; one named entry per credential; stored before the upstream change; every act can be rerun
and resumes; fail closed; the backend is chosen by the harness (`select_adapter` reads the running
system, never configuration or the environment); **a no-exposure scan follows every act**
(`ExposureGuard`, with `WatchedProvider` holding every secret the act reads or writes); reports carry
fingerprints only.

## The Windows adapter

- **Supervision:** the supervisor joins a new Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`
  before it starts the service and holds the job's only handle; breakaway is not allowed (`JOB_UNSAFE`
  otherwise). The managed environment ends on an explicit stop, when the supervisor exits or is
  killed, and with the user's session.
- **Inspection:** the kernel's TCP and UDP tables (`GetExtendedTcpTable`, `GetExtendedUdpTable`) with
  each row's owning process; the process token's elevation, elevation type and integrity level;
  process identity as pid plus creation time. Standard library `ctypes` only; psutil is not used.
- **Verified bytes:** a binary is hashed through a handle that shares read only, and the process starts
  while that handle is held.
- **Credentials:** Credential Manager generic credentials (`CredWriteW`, `CredReadW`, `CredDeleteW`);
  `ERROR_NO_SUCH_LOGON_SESSION` is `CREDENTIAL_PROVIDER_LOCKED`. F-06.3 moves the providers to
  `integrations/credentials/`.

## Commands

```
<tools python> -I -B -m unittest discover -s integrations/platform/tests -v   # task platform:test
```

## Not yet verified

- Linux and macOS (F-06.4, F-06.5).
- What ends the managed environment on a sign-out or a reboot (declared, rehearsed in F-06.6).
- `CREDENTIAL_PROVIDER_LOCKED` in a real session without a credential store (fakes only).
