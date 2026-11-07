# Host-loopback Gitea (`gitea_host.py`)

Plan leaf F-06.1, blueprint section
[`#infrastructure-state`](../../AI_Engineering_Open_Source_Blueprint_Architecture_Deep_Review_2026-10-31.html#infrastructure-state),
decisions [0007](../../decisions/0007-role-token-matrix-and-revocation-contract.md) and
[0009](../../decisions/0009-managed-data-root-and-configuration-contract.md). Qualification record:
[`evidence/F-06.1-gitea-loopback.md`](../../evidence/F-06.1-gitea-loopback.md).

Gitea's official Windows release binary runs on the Owner's host, bound to `127.0.0.1` only, as the
current Windows user without elevation, with no WSL, VM, Windows service, scheduled task, PATH,
registry or firewall change. Everything it uses comes from the [managed data root](../paths/README.md);
nothing is written into the checkout. Windows only.

## Files

| Path | What |
|---|---|
| `gitea_host.py` | The lifecycle command line: `install`, `up`, `down`, `status`, `verify`, `identities`, `finish-first-login` (and the internal `supervise`) |
| `tests/test_gitea_host.py` | Pin, layout, `app.ini`, acquisition, the binary lock, identities and first login with fakes; the Job Object, socket table and token code against real child processes; an opt-in live lifecycle test |
| `../../composition/lock/components.lock.json` | The pin: `release_assets` entry `gitea-28.3.0-windows-amd64.exe` (sha256, URL, checksum sources) |

## Commands

From the repository root (`task gitea:<name>`):

```
python -I -B integrations/gitea/gitea_host.py install [--port N] [--from-file EXE]   # network once: GitHub
python -I -B integrations/gitea/gitea_host.py up | down | status | verify
python -I -B integrations/gitea/gitea_host.py identities
python -I -B integrations/gitea/gitea_host.py finish-first-login
python -I -B -m unittest discover -s integrations/gitea/tests -v                    # task gitea:test
```

Exit 0 done, 1 failed, 2 refused (a stable code). Every command prints JSON and never a secret.

## Where everything lives

| What | Category | Path below the root |
|---|---|---|
| The verified binary and its `aieh-asset/1` record | `assets` | `assets/release-binaries/gitea/28.3.0/` |
| `app.ini` (class E: holds Gitea's secrets) | `gitea` | `persistent/gitea/custom/conf/app.ini` |
| SQLite database, sessions, queues, indexers, avatars, git `HOME` | `gitea` | `persistent/gitea/data/` |
| Repositories | `gitea` | `persistent/gitea/repositories/` |
| The host record (`aieh-gitea-host/1`: version, pin, port) and the run record (`aieh-gitea-run/1`) | `gitea` | `persistent/gitea/aieh-gitea-host.json`, `persistent/gitea/run/supervisor.json` |
| Gitea's log, its console output, the supervisor's output | `logs` | `persistent/logs/gitea/` |
| `TMP`/`TEMP` of Gitea and its git children; download staging | `tmp` | `ephemeral/tmp/gitea/` |

Gitea needs no install step, so it runs from its asset and `installs` is not used. Gitea is always
started with `--work-path`, `--custom-path` and `--config`, so it writes nothing next to its binary.

## The binary

`install` downloads the release asset into `tmp/gitea/`, hashes it while it streams, and moves it into
the asset directory only when the sha256 equals the lock's pin; then it writes the asset record.
Before every execution, the binary is opened with a share mode that allows reading only (no writer,
rename or delete), hashed through that handle against the pin and the record, and the process is
started while the handle is held. A file that does not match is never executed.

## Configuration

`install` writes `app.ini` once (exclusive create) with secrets from Gitea's own
`gitea generate secret` (`SECRET_KEY`, `INTERNAL_TOKEN`, `JWT_SECRET`), held in memory until written:
`HTTP_ADDR=127.0.0.1` on the fixed port 13300 (`--port` at install), `DISABLE_SSH`, no built-in SSH
server, `DISABLE_REGISTRATION`, `REQUIRE_SIGNIN_VIEW`, `OFFLINE_MODE`, `INSTALL_LOCK`, SQLite in
`data/`, mailer, update checker, federation, OpenID, the OAuth2 provider, Actions and LFS off.
Gravatar and federated avatars are not set in `app.ini`: Gitea 28 moved them to its database and
ignores the `[picture]` keys; `OFFLINE_MODE` disables them by default (avatars are served locally).

Gitea 28 also starts its own **egress-policy proxy** (`[security] EGRESS_MODE`, default `lax`) on
`127.0.0.1` with a kernel-assigned port. It answers unauthenticated requests with
`407 Proxy Authentication Required`. `verify` identifies it and requires every listener to be on
`127.0.0.1`.

## The managed environment

`up` starts a supervisor (`gitea_host.py supervise`, detached, under the current user). The
supervisor creates a Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` (no breakaway), puts
itself into it, and only then starts Gitea, which is therefore born inside the job. The job's handle
is not inheritable and is held by the supervisor alone, so when the supervisor ends, cleanly or by
`TerminateProcess`, the kernel closes the job and ends Gitea and any git child. `down` asks Gitea to
stop through its own `gitea manager shutdown`, waits on both process handles, and terminates the
supervisor only when Gitea does not stop within 60 s. Process identity is the pid plus its creation
time, recorded in the run record.

## Identities and first login

`identities` (Gitea running) creates `aieh-site-admin` (administrator) and `aieh-owner`
(non-administrator) with `gitea admin user create --random-password --must-change-password=true`,
e-mail `@localhost.invalid`. Gitea generates each temporary password (crypto/rand, 24 characters).
The CLI's output is captured into memory, never shown; the password goes by `CredWriteW` into one
generic Windows Credential Manager entry (`AIEH Gitea site-admin (temporary)`,
`AIEH Gitea owner (temporary)`, persisted to the local machine). No password is on any command line.

The Owner then signs in at `http://127.0.0.1:13300/` with each temporary password, read from
Control Panel, Credential Manager, Windows Credentials, and Gitea forces a new password.
`finish-first-login` then checks that neither account still must change its password, that each
temporary password no longer signs in (HTTP basic authentication against `/api/v1/user`) and occurs
in no file of the managed root or of the checkout (UTF-8 and UTF-16), and only then deletes the two
entries. The final passwords exist only as Gitea's password hashes.

## Not yet verified

- Anything but Windows 11 on x86_64.
- Gitea's egress proxy beyond the 407 answer, and the effective `EGRESS_MODE` policy.
- The Gitea-dependent role-token behaviour (bots, scopes, branch protection) of S-01.2.2.
