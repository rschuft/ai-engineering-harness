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

Since plan leaf F-06.2, `gitea_host.py` composes the **host-service lifecycle contract** and the
platform adapter of [`integrations/platform/`](../platform/README.md) (draft decision 0011): every process,
Job Object, listener, token and Credential Manager call goes through the adapter, and the contract
defines the verbs, the records and the refusal codes. Windows record:
[`evidence/F-06.2-platform-windows.md`](../../evidence/F-06.2-platform-windows.md). Since F-06.3 the
credential provider is [`integrations/credentials/`](../credentials/README.md), which the adapter
supplies through the harness's fail-closed factory
([`evidence/F-06.3-credential-provider.md`](../../evidence/F-06.3-credential-provider.md)).

## Files

| Path | What |
|---|---|
| `gitea_host.py` | The lifecycle command line: `install`, `up`, `down`, `restart`, `status`, `inspect`, `verify [--readiness]`, `identities`, `finalize-credentials`, `upgrade --to VERSION`, `recover`, `uninstall` (and the internal `supervise`); composes the platform adapter and its credential provider |
| `gitea_roles.py` | Role credentials (S-01.2.2): `provision`, `fixture [--admin-merge-probe]`, `escape-probe`, `rotate ROLE`, `retire ROLE`, `status`; Owner act OA-30's module `authorization-repository --owner-act OA-30` (plan leaf E-05.7, [below](#the-authorization-repository-e-057-owner-act-oa-30)); one total declaration per repository (`DECLARATIONS`: `fixture_declaration()` and `authorization_declaration()`, from `protection_rules()`, `repository_settings()`, `collaborators()` and the teams) and the protection auditor's reach (`AUDITED_REPOSITORIES`) |
| `protection_check.py` | The protection check before and after each protected merge (Owner decision OA-16; decision 0012 point 6): `verify OWNER/NAME`, and `verify()` for the authorization recorder ([below](#the-protection-check-oa-16)) |
| `tests/test_lifecycle.py` | The composition over the contract (F-06.2): the moved names, the platform asset key and `PLATFORM_MISMATCH`, both run-record formats, readiness, `inspect`, the transitions over a real SQLite database and `app.ini` in a temporary root, and the I7 scan of `main` |
| `tests/test_gitea_roles.py` | Bots, tokens, custody, fixture, revocation and rotation with a fake CLI and a fake API; the guest profile declares no path to a token store |
| `tests/test_authorization_live.py` | Opt-in (`AIEH_GITEA_AUTHZ=1`, `task gitea:authz`) allowed and forbidden calls of each bot token against the running Gitea. The protection auditor's writes (OA-16 Act C) are made non-mutating and must be refused by its scope: the fixture's routes on an absent repository, absent users and tokens, bodies Gitea rejects (`Required`), and `git push --dry-run` of a non-fast-forward to main and of deletions of absent branches; two are not sent and fail "not exercised" (the web sign-in form, the runner registration token; covered by the protection-audit negative phase). A circuit breaker sends no write of any role after the first unexpected acceptance and fails the run |
| `tests/test_transport_live.py` | Opt-in (`AIEH_GITEA_TRANSPORT=1`, `task gitea:transport`) the push matrix replayed through the repository module (F-10.6). The protection auditor's five pushes are updates the module withholds before sending (not a fast-forward, or the deletion of an absent branch) and must be refused at the receive-pack advertisement (HTTP 403); none is unexercised. The same circuit breaker |
| `tests/live_breaker.py` | The circuit breaker shared by those two suites (each holds its own) and the auditor's probe record |
| `tests/test_live_matrix_safety.py` | Those two suites' write safety offline (OA-16 Act C), run through unittest against a fake Gitea API (scopes; past a broken scope check: accepting, or validating as 28.3.0's binding and handlers are modelled), a fake git, and a smart-HTTP server on loopback (the module's pushes, and real `git push --dry-run`): the breaker stops every later write of every role, each auditor write refused or rejected with nothing created, the unexercised ones reported, and the other roles' requests equal to those of 7995a75 (`tests/live_matrix_7995a75.json`) |
| `tests/live_matrix_7995a75.json` | The other roles' requests of the two suites at commit 7995a75, recorded by `test_live_matrix_safety.record_golden` |
| `tests/protection_fake.py` | A fake Gitea 28.3.0 of what the protection auditor reads of one declared repository (the fixture by default, or the authorization repository): token and scope rules, `reqAdmin`, the 37-field rule view, the repository, branch, collaborator, permission, team and deploy-key views, faults; also used by the authorization recorder's fake |
| `tests/test_protection_check.py` | The protection check against the fake: the closed list pinned to 28.3.0, verified, each field's drift, the rule set and precedence, the settings, roster, teams and deploy keys, every unverifiable state, the session's fixed reads, the keep-alive connection and the command line over loopback; one declaration entry per repository (the authorization repository's its own, changed without the fixture's; `NOT_DECLARED` for any other repository or branch; the fixture still verifying with its recorded baseline), and the verified, field, rule-set, precedence and repository drift classes run again on the authorization repository (`Ledger...`) |
| `tests/test_authorization_repository.py` | Owner act OA-30's module on fakes (never run live by the suite): every step in order as the site administrator by basic authentication with no token minted, the read-back field for field, the auditor's check and baseline, the fixture's recorded baseline, each stop condition with nothing sent after it, the idempotent second run, the refusal without `--owner-act OA-30`, the read-only receipt check on throwaway stores, the command line |
| `tests/test_protection_audit_live.py` | Opt-in, two phases, each an Owner act (`AIEH_PROTECTION_AUDIT_LIVE=negative` or `=qualify`): the auditor's token is refused every write and reaches nothing outside its repository; the check detects injected drift and its restoration, one explicit sequence (OA-16 Act D) that stops at the first failed or uncertain check and sends no later injection (its baseline digest `AIEH_PROTECTION_AUDIT_BASELINE` when set, else the first verdict's). Each write probe is harmless (it repeats a value just read, or names an absent object) or made non-mutating (a body Gitea's validation rejects; git pushes the repository module refuses before sending an update: not a fast-forward, or deleting an absent branch); none is unexercised. The first security failure trips a circuit breaker: no later write is sent, in any class, and the run fails. Run once each on 2026-11-12 (OA-16 Acts C and D) |
| `tests/test_protection_audit_live_safety.py` | The negative phase's write safety offline (OA-16 Act C): the circuit breaker, each probe against a fake Gitea that lets writes past a broken scope check (accepting, rejecting, or validating as 28.3.0's body binding and handlers are modelled), the wider snapshot, and the git push probes through the repository module against a smart-HTTP server on loopback |
| `tests/test_protection_audit_qualify_safety.py` | The qualify phase's stop rules offline (OA-16 Act D): the live method against a fake Gitea with the site administrator's routes and the real check through a scripted verifier; a full pass sends exactly five injections and five restorations in order; a failing precondition sends no mutation; after a failed restoration, a read-back difference, an unexpected verdict or digest, a missing or unnamed drift, a non-2xx injection or an exception no later injection is sent, one restoration is attempted, nothing is retried |
| `tests/test_gitea_host.py` | Pin, layout, `app.ini`, acquisition, the binary lock, identities and first login with fakes; the Job Object, socket table and token code against real child processes; an opt-in live lifecycle test (install, up, verify and its readiness record, inspect, restart, down, uninstall, a supervisor kill, recover) on a fixture instance |
| `../../composition/lock/components.lock.json` | The pin: `release_assets` entry `gitea-28.3.0-windows-amd64.exe` (sha256, URL, checksum sources) |

## Commands

From the repository root (`task gitea:<name>`):

```
python -I -B integrations/gitea/gitea_host.py install [--port N] [--from-file EXE]   # network once: GitHub
python -I -B integrations/gitea/gitea_host.py up | down | restart | status | inspect | verify [--readiness]
python -I -B integrations/gitea/gitea_host.py identities
python -I -B integrations/gitea/gitea_host.py finalize-credentials
python -I -B integrations/gitea/gitea_host.py upgrade --to VERSION [--from-file EXE] | recover | uninstall
python -I -B integrations/gitea/gitea_roles.py provision | fixture [--admin-merge-probe] | escape-probe | rotate ROLE | retire ROLE | status
python -I -B integrations/gitea/gitea_roles.py authorization-repository --owner-act OA-30   # Owner act OA-30 only
python -I -B integrations/gitea/protection_check.py verify OWNER/NAME [--base BRANCH] [--port N]   # task gitea:protection-check
python -I -B -m unittest discover -s integrations/gitea/tests -v                    # task gitea:test
AIEH_GITEA_AUTHZ=1 python -I -B -m unittest discover -s integrations/gitea/tests -p test_authorization_live.py -v   # task gitea:authz
AIEH_PROTECTION_AUDIT_LIVE=negative|qualify <tools python> -I -B -m unittest discover -s integrations/gitea/tests -p test_protection_audit_live.py -v
```

Exit 0 done, 1 failed, 2 refused (a stable code). Every command prints JSON and never a secret.
Every act ends with the **I7 no-exposure scan** (credential invariant 7): before anything is shown, its
report and its message are searched for every secret the act held (each secret the credential
provider read or wrote during the act, and the `app.ini` secrets `verify` read), as UTF-8 and UTF-16LE,
and for anything token-shaped (40 hex digits). A hit withholds the output and exits 1 with
`EXPOSURE_FOUND`; a clean scan prints one line on standard error,
`I7 no-exposure scan: clean (N secrets held; M outputs scanned)`.

## The lifecycle contract's verbs

| Verb | Here | What it does |
|---|---|---|
| install | `install` | the root, the verified asset, `app.ini` and the host record (now with `platform.asset_key`) |
| up, down, status | `up`, `down`, `status` | unchanged from F-06.1 |
| restart | `restart` | `down` (when running) and `up` under a write-ahead transition record |
| inspect | `inspect` | read-only: the `aieh-platform/1` record, the desired, staged and running versions, both processes with their listeners and user identity, the supervision record, the transitions |
| verify | `verify [--readiness]` | the F-06.1 proof set, unchanged; `--readiness` prints it as an `aieh-readiness/1` record with platform-neutral check names and the platform |
| provision | `identities`; `gitea_roles.py provision` | the human accounts' temporary credentials; the role bots' tokens |
| rotate | `finalize-credentials`; `gitea_roles.py rotate ROLE` | temporary to final (human accounts); revoke and re-issue (a role) |
| retire | `gitea_roles.py retire ROLE` | revoke a role's token, prove its next call is refused (401), then delete its entry; resumes; the account is kept |
| upgrade | `upgrade --to VERSION` | a pinned version only; stage and verify its asset beside the current one, stop, back up `gitea.db` (SQLite backup API) and `app.ini` into `persistent/gitea/backups/<transition>/`, make it desired, start it, check readiness; a failure before readiness rolls back automatically from that backup |
| recover | `recover` | reconciles the actual state with the pending transition first, then resumes it (restart, uninstall) or completes or rolls back an upgrade |
| uninstall | `uninstall` | refused while running (`UNINSTALL_RUNNING`); empties `ephemeral/tmp/gitea/` and deletes nothing under `persistent/` and no asset. On Windows nothing is registered with the system, so nothing else is removed and `up` works again afterwards |

The transition records (`aieh-service-transition/1`) are in `persistent/gitea/run/transitions/`, one
file per transition, written before any process is replaced and never deleted. While one is pending,
`restart`, `upgrade` and `uninstall` are refused with `TRANSITION_PENDING`. The lock pins one Windows
version today, so a real cross-version upgrade has not run: `upgrade` is exercised with fixture assets
(plan leaf F-06.6 rehearses it on a disposable instance).

## Where everything lives

| What | Category | Path below the root |
|---|---|---|
| The verified binary and its `aieh-asset/1` record | `assets` | `assets/release-binaries/gitea/28.3.0/` |
| `app.ini` (class E: holds Gitea's secrets) | `gitea` | `persistent/gitea/custom/conf/app.ini` |
| SQLite database, sessions, queues, indexers, avatars, git `HOME` | `gitea` | `persistent/gitea/data/` |
| Repositories | `gitea` | `persistent/gitea/repositories/` |
| The host record (`aieh-gitea-host/1`: version, pin, port, optional `platform.asset_key`) and the run record (`aieh-service-run/1`; one written before F-06.2 is `aieh-gitea-run/1`, still read) | `gitea` | `persistent/gitea/aieh-gitea-host.json`, `persistent/gitea/run/supervisor.json` |
| The transition records (`aieh-service-transition/1`) and the upgrade backups | `gitea` | `persistent/gitea/run/transitions/`, `persistent/gitea/backups/` |
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

The checkout's file list (`checkout_files`) is the list `git ls-files --cached --others
--exclude-standard` gives, read in process by the shared repository-access module
([`integrations/repository/`](../repository/README.md), decision 0014 row R9: its `listing`, under the
`host` configuration policy, so the excludes file git reads for this checkout applies); no git is
launched. The module's contract suite and `TestCheckoutFiles` hold it equal to git's listing on this
checkout and on an ignore-rule corpus, and never a strict subset of it, so the scan misses no file git
would list. A checkout that cannot be listed (not a work tree, no Dulwich in the interpreter) fails with
`CHECKOUT_UNLISTED` (exit 1), never as an empty scan; `verify` and `finalize-credentials` therefore run
under the tools interpreter (`task gitea:verify`, `task gitea:finalize-credentials`).

**Why this mechanism.** `gitea admin user change-password --password` would put a password on a
command line, so it is not used. The web flow is Gitea's own supported forced change. It needs no
token and no administrator. A password is never on a command line, in an environment, in a log or
in output.

The final credentials are harness-held, for administration only: `finalize-credentials` and the
fixture administration (`gitea_roles.py fixture`) read the site administrator's entry, and nothing
reads the Owner account's yet. How the Owner identity is used internally is still to be decided. No
bot, test or ordinary Builder or Reviewer context reads either entry.

**The credential provider.** Callers reach credentials through `CredentialProvider` (`get`, `set`,
`delete`, `exists`; the contract's interface) from `credential_provider()`. The provider is chosen by the
harness's factory in [`integrations/credentials/`](../credentials/README.md) (F-06.3), which the
adapter supplies: on Windows `WindowsCredentialProvider`, Credential Manager (`CredWriteW`, `CredReadW`,
`CredDeleteW`; secrets as UTF-16LE), moved there and still importable from `gitea_host`; keyring
is never instantiated on Windows. A session without a credential store is refused with
`CREDENTIAL_PROVIDER_LOCKED`, and no qualified provider with `NO_CREDENTIAL_PROVIDER`. An entry whose
target, user, comment or secret is over its Windows limit is refused with `CREDENTIAL_FIELD_LIMIT` before
`CredWriteW` is called ([the limits](../credentials/README.md#windows-credential-field-limits)).

**Receipts of credential acts (F-06.3).** Every rotate or retire act writes an integration-store receipt
(decision 0007 point 5: fingerprint, role, trigger, revoker, affected attempts; fingerprints only) and
reads it back: `finalize-credentials` one per account, `gitea_roles.py rotate ROLE` and `retire ROLE` one
per run, a resumed run included. The receipt is reserved before anything changes (without it the act does
not start), marked dispatched before the upstream change, then confirmed with the outcome (failed when
the harness observed that the change did not apply, unknown when the outcome is uncertain) and read back;
an act whose receipt is not read back as written fails with `CREDENTIAL_RECEIPT_UNREAD`. The command line
writes into `persistent/state/integration/integration.sqlite` of the managed root (the integration
store's default location under decision 0009); a caller that passes its own context passes its own store.

## Role credentials (S-01.2.2)

Record: [`evidence/S-01.2.2-segregated-credentials.md`](../../evidence/S-01.2.2-segregated-credentials.md);
matrix: [`policy/role-tokens.json`](../../policy/README.md).

- **Accounts.** `provision` creates, with Gitea's CLI, one account per role that holds a Gitea
  credential: `aieh-bot-planner`, `aieh-bot-builder`, `aieh-bot-reviewer`, `aieh-bot-verifier` and,
  since Owner decision OA-16 (provisioned on 2026-11-12, Act A), the protection auditor
  `aieh-bot-protection-audit` (`admin user create --user-type Bot --restricted`). They are not administrators and have no
  password, so they cannot sign in interactively. An existing account that is not a
  non-administrator Bot is refused.
- **Tokens.** Each is minted with `admin user generate-access-token --raw` and the narrowest scope
  Gitea 28.3.0 can express: `write:repository` for the planner, builder and reviewer, and
  `read:repository` for the verifier and the protection auditor. Gitea's scopes are categorical; the per-repository and
  per-branch limits come from collaborator permission and branch protection. The CLI's output is
  captured in memory and must be exactly one token, which the credential provider writes into the
  entry `AIEH Gitea bot <role>`. Reports carry a fingerprint (`sha256:` and 16 hex digits)
  only. An existing entry is kept.
- **The entry before the token.** `provision` checks every requested role's entry, and `rotate` the
  role's new entry, exactly as it will be written (target, user, comment and a 40-hex-digit token's
  size) against the [Windows credential field limits](../credentials/README.md#windows-credential-field-limits)
  before anything changes: an entry that does not fit is refused with `CREDENTIAL_FIELD_LIMIT` before
  any account is created, any token is minted or revoked, or any receipt is reserved. The check writes
  nothing, and passing it is no guarantee: if the store fails after the mint all the same, the new token
  revokes itself once (`DELETE /api/v1/token`, then its next call must get 401), with no retry of the
  store, the revocation or the mint, and the act fails with `TOKEN_STORE_FAILED` (revocation confirmed;
  nothing stored) or `TOKEN_ORPHANED` (not confirmed: the message names the token's name, account and
  fingerprint, which an administrator must delete). The token's Gitea id is not known (the CLI's `--raw`
  output is the value alone). Each entry's comment names the account, the scopes, the instance and the
  custody, and fits the 256-character limit with at least 16 characters to spare on any port (since
  2026-11-11, when the protection auditor's 271-character comment made `CredWriteW` fail with 1734 after
  its token was minted).
- **Rotation.** `rotate ROLE` revokes the token through Gitea's `DELETE /api/v1/token`, proves that
  its next call gets 401, mints a new one and replaces the entry. It resumes as `retire` does: a token
  Gitea already refuses (401, revoked earlier) is not revoked again, and the new one is minted.
  Rotation and revocation of a standing bot token are this administrative lifecycle's acts, on
  defined security and lifecycle triggers, never on routine attempt completion (decision 0007
  point 4; the Owner's correction of 2026-11-11). Gitea 28.3.0 has no token lifetime and gives the
  dispatcher no way to issue a replacement, so the dispatcher only uses the standing token per
  attempt and releases its in-memory reference at the end, which revokes nothing
  ([`integrations/dispatch/`](../dispatch/README.md#the-stages-role-token-e-0133)).
- **Fixture.** `fixture` acts as `aieh-site-admin` by HTTP basic authentication with its
  harness-held password, read from the credential provider into memory; it mints no token. It creates the
  private organization `aieh-authz-fixture` and repository `authz`, applies the repository's settings
  (`repository_settings()`: private, not archived, default branch `main`, merge commits the only merge
  style, no manual merge; `PATCH /repos/{owner}/{repo}`), the collaborators (planner and builder write,
  reviewer and verifier read, `aieh-owner` write, the protection auditor admin) and three protection
  rules, each total over the 34 fields of Gitea 28.3.0's rule (`protection_rules()`: every field named, the
  rest at Gitea's zero value, so re-applying resets a drifted field):
  - `main` (priority 1): no push or force-push; only `aieh-owner` merges; one approval from the reviewer
    bot; a rejected review blocks; a branch behind `main` cannot be merged (`block_on_outdated_branch`);
    the administrator's merge override blocked;
  - `work/*` (priority 2): the planner and builder bots push; only `aieh-owner` merges;
  - `**` (priority 3): nobody pushes; only `aieh-owner` merges.

  On every rule the bypass allowlist is disabled and empty, and stale approvals are not dismissed until
  G-03.1 decides the authorization branch's policy. The declaration on the live fixture changes only when
  `fixture` is run again (an Owner act; last run on 2026-11-12, OA-16 Act B, which applied the total
  declaration).

  It reports that the administrator holds no token afterwards. `--admin-merge-probe` also has the
  site administrator try to merge a proposal PR, which must be refused. Gitea refuses every API call
  of an account that must still change its password, so `fixture` runs after `finalize-credentials`.
- **Escape probe.** `escape-probe`, a separate Owner act and never part of `provision` or `fixture`, acts
  as the site administrator as `fixture` does (basic authentication, no token; the report shows none
  afterwards) and creates the organization's second repository, `aieh-authz-fixture/escape-probe`:
  private, empty (`auto_init` false) and with no collaborators. The protection auditor's live negative
  test reads its rules by default and must be refused (`test_protection_audit_live.py`;
  `AIEH_PROTECTION_AUDIT_OTHER_REPOS` names others instead). It reads the organization and that repository
  only, its one write is the repository's creation, and it never addresses `authz`. An existing
  `escape-probe` that is private, empty, not archived and without collaborators is reported and left
  unchanged; one in any other state is refused (`ESCAPE_PROBE_STATE`) and left unchanged; a missing
  organization is refused (`FIXTURE_MISSING`: run `fixture` first).
- **The authorization repository (E-05.7, Owner act OA-30).** See [below](#the-authorization-repository-e-057-owner-act-oa-30).
- **Live tests.** `task gitea:authz` reads every role's token into memory (the protection auditor's
  too; without its entry the suite skips naming the missing entry) and probes what each
  may and may not do; the fixture-dependent classes skip while the fixture is absent, and the executor
  test is not applicable (G-04.2.1). The protection auditor's write probes there and in `task
  gitea:transport` are non-mutating if Gitea wrongly accepted them, or not sent (two, reported "not
  exercised"); the first unexpected acceptance by any role trips a circuit breaker after which no write is
  sent and the run fails (OA-16 Act C; see the suites' docstrings).

## The authorization repository (E-05.7, Owner act OA-30)

[Decision 0022](../../decisions/0022-authorization-repository-the-one-ledger-provisioned-for-d1.md): real Owner
authorizations are recorded on one dedicated repository, `aieh-authorization/authorizations`
(`AUTHORIZATION_ORG`, `AUTHORIZATION_REPO`: a private organization of its own; the name is permanent and nothing
else spells it), never on the fixture. Its declaration is an entry of its own in `DECLARATIONS`
(`authorization_declaration()`): today the qualified fixture's total declaration (the same rules, settings,
collaborators and Owners team), so that G-03.1 can change it without the fixture's. Its collaborators are those of
OA-30 (b): the four bots with the fixture's permissions, the protection auditor repository administrator (the
auditor's reach, `AUDITED_REPOSITORIES`, becomes the fixture and this repository), and `aieh-owner` write.

`authorization-repository --owner-act OA-30` is OA-30's administration act, built and tested on fakes and **not
run**. It refuses (`OWNER_ACT_REQUIRED`, nothing read or sent) unless `--owner-act OA-30` names the act. Then:

1. read-only, before any write: the managed integration store holds no `owner-authorization/v1/` receipt
   (`recorder_receipts`: SQLite `mode=ro` and `query_only`, never migrated; `RECORDER_RECEIPTS_PRESENT`), and the
   bots and `aieh-owner` exist (`BOTS_MISSING`, `OWNER_MISSING`);
2. as `aieh-site-admin` by basic authentication with the harness-held password read into memory (no token
   minted): the private organization, the repository (auto-initialized, default branch `main`), its settings
   (`PATCH`), its collaborators, its three protection rules, in that order;
3. the read-back as the administrator, compared field for field with the declaration: the organization's
   visibility and team-access setting, the repository's settings, the collaborators and their permissions, every
   rule's 34 fields, the teams, no deploy key, `main` holding its initial commit alone (its head has no parent)
   and no pull request in any state (`READBACK_DIFFERENT`);
4. the administrator holds no token afterwards (`ADMIN_HOLDS_TOKEN`);
5. `protection_check.verify` of the repository as the protection auditor, read-only: `verified`, its baseline
   digest reported (`PROTECTION_NOT_VERIFIED`);
6. the fixture still `verified` with its recorded baseline, `protection_check.RECORDED_BASELINES`
   (`FIXTURE_NOT_VERIFIED`).

Any non-2xx answer stops it (`API_UNEXPECTED`, naming what was sent before it), as does each check above:
nothing further is sent, nothing is undone or retried. An existing organization or repository is never adopted or
modified: one that reads back as declared and verifies is reported (`already present; nothing written`), so a
second run writes nothing; one in any other state is refused (`AUTHORIZATION_REPOSITORY_EXISTS`) with nothing
written. It never merges, opens a pull request, injects drift, runs a negative control or records an Owner
statement on the repository. Its report carries no commit id or token and is shown unredacted (its digests have
64 hex digits); the I7 scan withholds it if anything token-shaped is in it.

## The protection check (OA-16)

Owner decision OA-16 (2026-11-11; [recommendation](../../evidence/P-04.2-protection-check-recommendation.md),
option 2; record [`evidence/P-04.2-protection-verifier.md`](../../evidence/P-04.2-protection-verifier.md)).
Decision [0012](../../decisions/0012-owner-authorization-channel-and-gitea-owner-identity.md) was
accepted on 2026-11-12, after P-04.2's live exercise. `protection_check.py` is a bounded read-only
adapter of this integration, not a policy service:
the authorization recorder ([`integrations/owner`](../owner/README.md)) asks it in process as the last read
before each merge and once more after the read-back, and merges only on `verified`.

**The auditor.** Gitea 28.3.0 serves the branch protection rules to repository and site administrators only
(`routers/api/v1/api.go`: `branch_protections` behind `reqToken(), reqAdmin()`), and `aieh-owner` is
neither. The check reads as `aieh-bot-protection-audit`: a restricted Bot without a password, collaborator
with `admin` permission on the repositories it audits only (`AUDITED_REPOSITORIES`: the fixture, and the
authorization repository once OA-30 is performed), one token of scope exactly `read:repository`
(credential `cred-gitea-protection-audit`, entry `AIEH Gitea bot protection-audit`; its custodian is the
recorder). Gitea decides a token's required scope by HTTP method (`tokenRequiresScopes`: GET read; POST,
PUT, PATCH, DELETE write), also for a token used as a basic-authentication password, so the token can
change no rule, collaborator or setting, push, merge or sudo. It can delete itself (`DELETE /api/v1/token`
needs no scope), which the check never sends; a deleted token only makes the check fail closed. No site
administrator identity, no administrator credential of `aieh-owner` and no broader permission is used.

**The closed list.** Every read is a fixed GET (anything else is a `ValueError` before sending):

| What | Read from | Drift when | Unverified when |
|---|---|---|---|
| The auditor | `GET /token`; the repository view's `permissions` | - | not 200 (401: `CREDENTIAL_REJECTED`); its login is not `aieh-bot-protection-audit`, its scopes not exactly `read:repository`, or `permissions.admin` not true (`AUDITOR_INVALID`) |
| Every rule, 34 fields (`PROTECTION_FIELDS`: push, force-push, merge and bypass allowlists, the review gate, outdated branch, status checks, signed commits, file patterns, the admin override, name, priority) | `GET .../branch_protections` | a field differs from `protection_rules()` (lists as multisets; `null` equals `[]`) | a field outside the 37 of 28.3.0's view, a missing one, a value of another type, `branch_name` not what Gitea derives, a repeated name |
| The rule set | same | a declared rule missing, any other rule | - |
| Precedence | the rules, and `GET .../branches/main` (`effective_branch_protection_name`, shown to administrators) | the rules matching `main`, in Gitea's order, or the enforced one, differ from the declaration | Gitea's enforced rule is not the first its own order gives at the pin, or a glob the check cannot evaluate (`PRECEDENCE_UNVERIFIED`) |
| Repository settings (`repository_settings()`) | `GET /repos/{owner}/{repo}` | a value differs | a top-level field outside 28.3.0's 70, or a required one missing; the repository answers under another name |
| Collaborators and their permissions | `GET .../collaborators` and `.../collaborators/{user}/permission` | the roster or a permission differs from `collaborators()` (permission as Gitea computes it, team membership included) | `X-Total-Count` is not the number listed; a permission outside Gitea's levels |
| Teams with access | `GET .../teams` | not exactly the Owners team with `owner` | a field outside 28.3.0's, a repeated name |
| Deploy keys (deploy tokens included) | `GET .../keys` | any | `X-Total-Count` is not the number listed |

Any read that is not 200, not JSON, of the wrong kind or lost is `READ_FAILED`; a missing entry is
`CREDENTIAL_MISSING`, an entry naming another account or not holding a token `CREDENTIAL_REFUSED` (both
before anything is sent); a repository without a declaration entry (`DECLARATIONS`: the fixture and the
authorization repository) is `NOT_DECLARED`. Each is
`unverified`, never `verified`. The verdict's digest is `sha256:` of the canonical observed values (never
a token, a time or a commit).

**Rule precedence at the pin** (`models/git/protected_branch_list.go`, read in the pinned source): Gitea
sorts a repository's rules by `priority` (lower first), then a plain name before a glob, then the earlier
created, and enforces the first rule that matches the branch; a plain name matches case-insensitively, a
glob through `modules/glob` with `/` as the separator (`*` within a segment, `**` across, `?`, classes,
alternatives). A rule created without a priority gets the highest plus one. For `main` the declaration
gives `main` (1) then `**` (3); `work/*` does not match.

**Gitea's own merge-time enforcement** (`services/pull/check.go` `CheckPullMergeable`,
`services/pull/merge.go` `CheckPullBranchProtections`, `routers/private/hook_pre_receive.go`): at the merge
Gitea itself evaluates the rule row as it is then, twice (in the merge handler and in the pre-receive hook
of the merge push). It enforces the merge allowlist, the required approvals (from the approvals allowlist),
rejected reviews, official review requests, code-owner reviews, an outdated branch, required status checks,
protected files, signed commits and the recorder's `head_commit_id` (409 when the head moved), and it lets
an account on the bypass allowlist (or an administrator when the override is not blocked) force-merge past
those gates. It does not compare the rule with any declaration: a changed rule is enforced as changed; and
a manual merge (`Do: manually-merged`, when the repository allows it) is checked against the merge
allowlist only, which is why `allow_manual_merge` is declared false.

**Time of check to time of use.** No API spans the check and the merge. A repository or site administrator
can change a rule in between (about one request round-trip on host loopback); the recorder asks the check
again after the read-back and records both answers in the receipt, so a change that is not reverted within
the window is disclosed (`PROTECTION_CHANGED_AFTER_MERGE`), not prevented. Gitea 28.3.0 records protection
changes in its audit log only when they are made through its web pages, and shows the log through web pages
only, so the log corroborates, never controls (security finding `fd-protection-check-toctou`).

**Limits.** Team membership is not readable with `read:repository`: who belongs to the Owners team is not
compared. The allowlist names Gitea shows are resolved among the repository's current readers. Webhooks are
not read. The check reads a repository with a declaration entry of its own: the S-01.2.2 fixture, and the
authorization repository (E-05.7), whose entry G-03.1 completes.

## Not yet verified

- Anything but Windows 11 on x86_64 (Linux and macOS adapters: F-06.4, F-06.5).
- A real cross-version `upgrade` (one version is pinned), and the rehearsal of upgrade, recovery and
  uninstall on a disposable instance with a reboot or sign-out (F-06.6).
- `retire` against the running Gitea (fakes only).
- The protection check on any repository but the S-01.2.2 fixture: the authorization repository's declaration
  and OA-30's module (`authorization-repository`) have run against the fakes only; the repository does not exist
  until OA-30 is performed. Gitea's views in states the live runs did not produce (the check's
  `unverified` paths on the real Gitea are exercised against the fake only).
- The receipts of credential acts against the running Gitea and the managed root's integration store
  (fakes and a fixture store only, F-06.3).
- Gitea's egress proxy beyond the 407 answer, and the effective `EGRESS_MODE` policy.
- Gitea's audit logging (off by default).
- A credential provider other than Windows Credential Manager on a real host (keyring's Secret Service
  and Keychain backends: F-06.4, F-06.5).

Live-verified on 2026-11-07: `finalize-credentials` on the real instance, with its token remediation and
no-exposure scan ([F-06.1 section 8](../../evidence/F-06.1-gitea-loopback.md)); the fixture, the
administrator's blocked merge override and the full live authorization suite
([S-01.2.2](../../evidence/S-01.2.2-segregated-credentials.md)).

Live-verified on 2026-11-12 (OA-16 Acts A to D and P-04.2's live exercise: `evidence/bootstrap-log.md`,
Decisions; [P-04.2 section 17](../../evidence/P-04.2-authorization-recorder.md)): the protection auditor's
provisioning (`provision`), `fixture` applying the total declaration and `protection_check.py verify`
answering `verified`; `escape-probe` (created private, empty and without collaborators); the auditor's
negative tests (every write refused by its scope, the other repository's rules not readable) with
`gitea:authz` and `gitea:transport`; the qualification (five injected drifts, each detected and its
restoration verified); and the check before and after the authorization recorder's live merge.
