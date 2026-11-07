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
| `gitea_roles.py` | Role credentials (S-01.2.2): `provision`, `fixture [--admin-merge-probe]`, `rotate ROLE`, `status` |
| `tests/test_gitea_roles.py` | Bots, tokens, custody, fixture, revocation and rotation with a fake CLI and a fake API; the guest profile declares no path to a token store |
| `tests/test_authorization_live.py` | Opt-in (`AIEH_GITEA_AUTHZ=1`, `task gitea:authz`) allowed and forbidden calls of each bot token against the running Gitea |
| `tests/test_gitea_host.py` | Pin, layout, `app.ini`, acquisition, the binary lock, identities and first login with fakes; the Job Object, socket table and token code against real child processes; an opt-in live lifecycle test |
| `../../composition/lock/components.lock.json` | The pin: `release_assets` entry `gitea-28.3.0-windows-amd64.exe` (sha256, URL, checksum sources) |

## Commands

From the repository root (`task gitea:<name>`):

```
python -I -B integrations/gitea/gitea_host.py install [--port N] [--from-file EXE]   # network once: GitHub
python -I -B integrations/gitea/gitea_host.py up | down | status | verify
python -I -B integrations/gitea/gitea_host.py identities
python -I -B integrations/gitea/gitea_host.py finish-first-login
python -I -B integrations/gitea/gitea_roles.py provision | fixture [--admin-merge-probe] | rotate ROLE | status
python -I -B -m unittest discover -s integrations/gitea/tests -v                    # task gitea:test
AIEH_GITEA_AUTHZ=1 python -I -B -m unittest discover -s integrations/gitea/tests -p test_authorization_live.py -v   # task gitea:authz
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

## Role credentials (S-01.2.2)

Record: [`evidence/S-01.2.2-segregated-credentials.md`](../../evidence/S-01.2.2-segregated-credentials.md);
matrix: [`policy/role-tokens.json`](../../policy/README.md).

- **Accounts.** `provision` creates, with Gitea's CLI, one account per role that holds a Gitea
  credential: `aieh-bot-planner`, `aieh-bot-builder`, `aieh-bot-reviewer` and `aieh-bot-verifier`
  (`admin user create --user-type Bot --restricted`). They are not administrators and have no
  password, so they cannot sign in interactively. An existing account that is not a
  non-administrator Bot is refused.
- **Tokens.** Each is minted with `admin user generate-access-token --raw` and the narrowest scope
  Gitea 28.3.0 can express: `write:repository` for the planner, builder and reviewer, and
  `read:repository` for the verifier. Gitea's scopes are categorical; the per-repository and
  per-branch limits come from collaborator permission and branch protection. The CLI's output is
  captured in memory and must be exactly one token, which `CredWriteW` writes into a generic Credential
  Manager entry, `AIEH Gitea bot <role>`. Reports carry a fingerprint (`sha256:` and 16 hex digits)
  only. An existing entry is kept.
- **Rotation.** `rotate ROLE` revokes the token through Gitea's `DELETE /api/v1/token`, proves that
  its next call gets 401, mints a new one and replaces the entry. Gitea 28.3.0 has no token
  lifetime, so per-attempt rotation is the dispatcher's job (S-01.3.1).
- **Fixture.** `fixture` mints a token for `aieh-site-admin` with the CLI (scopes
  `write:organization,write:repository`), holds it in memory, and checks it first. It then creates the
  private organization `aieh-authz-fixture` and repository `authz`, the collaborators (planner and
  builder write, reviewer and verifier read, `aieh-owner` write) and three protection rules:
  - `main`: no push or force-push; only `aieh-owner` merges; one approval from the reviewer bot;
    the administrator's merge override blocked;
  - `work/*`: the planner and builder bots push;
  - `**`: nobody pushes.

  It revokes the token in every outcome and reports whether that worked.
  `--admin-merge-probe` also has the site administrator try to merge a proposal PR, which must be
  refused. Gitea refuses every API call of an account that must still change its password, so
  `fixture` works only after the Owner's first sign-in and `finish-first-login`.
- **Live tests.** `task gitea:authz` reads the four tokens into memory and probes what each may and
  may not do; the fixture-dependent classes skip while the fixture is absent, and the executor test
  is not applicable (G-04.2.1).

## Not yet verified

- Anything but Windows 11 on x86_64.
- Gitea's egress proxy beyond the 407 answer, and the effective `EGRESS_MODE` policy.
- The repository-level role-token behaviour of S-01.2.2: branch protection, merge allowlists,
  PRs and reviews (the fixture awaits the site administrator's first sign-in).
- The `--restricted` flag's effect, and the site administrator's path to revoke another account's token.
