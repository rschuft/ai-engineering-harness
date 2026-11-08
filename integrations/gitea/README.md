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
| `gitea_host.py` | The lifecycle command line: `install`, `up`, `down`, `status`, `verify`, `identities`, `finalize-credentials` (and the internal `supervise`); the credential provider |
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
python -I -B integrations/gitea/gitea_host.py finalize-credentials
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

## Identities and credential finalization

The Owner never signs in to Gitea, changes its passwords or opens Credential Manager: the harness
completes the credential lifecycle itself (Owner directive of 2026-11-07, which supersedes the manual
first sign-in of F-06.1).

`identities` (Gitea running) creates `aieh-site-admin` (administrator) and `aieh-owner`
(non-administrator) with `gitea admin user create --random-password --must-change-password=true`,
e-mail `@localhost.invalid`. Gitea generates each temporary password (crypto/rand, 24 characters).
The CLI's output is captured into memory, never shown; the password goes through the credential
provider into one entry (`AIEH Gitea site-admin (temporary)`, `AIEH Gitea owner (temporary)`). No
password is on any command line.

`finalize-credentials` then does, for the site administrator and then the Owner account:

1. generate a final password with `secrets.token_urlsafe(32)` and store it in the provider entry
   `AIEH Gitea site-admin` or `AIEH Gitea owner` **before** Gitea is changed, so a failure can never
   lose it (a rerun resumes from any intermediate state);
2. set it with Gitea's own forced change: sign in at `/user/login` with the temporary password.
   Gitea 28.3.0 answers a correct sign-in with 303 to `/`, not to the form; the next page request
   (`GET /`) answers 303 to `/user/settings/change_password`. The tool follows that redirect, requires
   Gitea itself to send the session to the form, and only then submits it. A wrong password answers
   200 with the sign-in form and stops the run. The passwords travel only in loopback form-post bodies;
3. with the new password (HTTP basic authentication), list and delete **every** access token of the
   account, then list again: a finalized human account holds no token (this revokes the
   site-administrator token that S-01.2.2's first fixture attempt could not revoke). This is enforced
   on the first run and on every rerun of a finalized account: a token still listed, even one whose
   deletion answered 204, fails with `TOKENS_REMAIN` (names only), and a listing afterwards that is not
   200 with a token list fails with `TOKEN_REVOCATION_UNVERIFIED` (`TOKEN_LIST_FAILED` is the listing
   before anything is deleted). Both entries stay, so a rerun resumes;
4. verify: the final password authenticates and Gitea no longer demands a change; the temporary
   password is rejected; the account's administrator flag is as expected;
5. delete the temporary entry;
6. search every file of the managed root (logs included) and of the checkout (tracked and untracked,
   not ignored; UTF-8 and UTF-16) and its own report for every temporary and final password, and fail,
   naming files only, on any hit (`PASSWORD_FOUND`). A search that could not cover everything fails too
   (`SECRET_SCAN_INCOMPLETE`, naming the paths): a directory of the managed root that cannot be listed
   or a non-empty file that cannot be read. An unreadable empty file (LevelDB's `LOCK`, held by the
   running Gitea) holds nothing and is not reported; a tracked file absent from the working tree holds
   no content and is listed in `absent_from_checkout`, not as a failure.

`verify`'s `no_gitea_secret_in_checkout` check fails in the same way on a file it could not read; its
`checkout_scan` output names the unreadable and absent paths.

**Why this mechanism.** `gitea admin user change-password --password` would put a password on a
command line, so it is not used. The web flow is Gitea's own supported forced change. It needs no
token and no administrator. A password is never on a command line, in an environment, in a log or
in output.

The final credentials are harness-held, for administration only: `finalize-credentials` and the
fixture administration (`gitea_roles.py fixture`) read the site administrator's entry, and nothing
reads the Owner account's yet. How the Owner identity is used internally is still to be decided. No
bot, test or ordinary Builder or Reviewer context reads either entry.

**The credential provider.** Callers reach credentials through `CredentialProvider` (`get`, `set`,
`delete`, `exists`). `WindowsCredentialProvider` implements it with Credential Manager (`CredWriteW`,
`CredReadW`, `CredDeleteW`; secrets as UTF-16LE). A cross-platform implementation can replace it
through `credential_provider()` without its callers changing.

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
  captured in memory and must be exactly one token, which the credential provider writes into the
  entry `AIEH Gitea bot <role>`. Reports carry a fingerprint (`sha256:` and 16 hex digits)
  only. An existing entry is kept.
- **Rotation.** `rotate ROLE` revokes the token through Gitea's `DELETE /api/v1/token`, proves that
  its next call gets 401, mints a new one and replaces the entry. Gitea 28.3.0 has no token
  lifetime, so per-attempt rotation is the dispatcher's job (S-01.3.1).
- **Fixture.** `fixture` acts as `aieh-site-admin` by HTTP basic authentication with its
  harness-held password, read from the credential provider into memory; it mints no token. It creates the
  private organization `aieh-authz-fixture` and repository `authz`, the collaborators (planner and
  builder write, reviewer and verifier read, `aieh-owner` write) and three protection rules:
  - `main`: no push or force-push; only `aieh-owner` merges; one approval from the reviewer bot;
    the administrator's merge override blocked;
  - `work/*`: the planner and builder bots push;
  - `**`: nobody pushes.

  It reports that the administrator holds no token afterwards. `--admin-merge-probe` also has the
  site administrator try to merge a proposal PR, which must be refused. Gitea refuses every API call
  of an account that must still change its password, so `fixture` runs after `finalize-credentials`.
- **Live tests.** `task gitea:authz` reads the four tokens into memory and probes what each may and
  may not do; the fixture-dependent classes skip while the fixture is absent, and the executor test
  is not applicable (G-04.2.1).

## Not yet verified

- Anything but Windows 11 on x86_64.
- Gitea's egress proxy beyond the 407 answer, and the effective `EGRESS_MODE` policy.
- Gitea's audit logging (off by default).
- A credential provider other than Windows Credential Manager.

Live-verified on 2026-11-07: `finalize-credentials` on the real instance, with its token remediation and
no-exposure scan ([F-06.1 section 8](../../evidence/F-06.1-gitea-loopback.md)); the fixture, the
administrator's blocked merge override and the full live authorization suite
([S-01.2.2](../../evidence/S-01.2.2-segregated-credentials.md)).
