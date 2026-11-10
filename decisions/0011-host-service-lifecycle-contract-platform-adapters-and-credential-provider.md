# 0011 - Host-service lifecycle contract, platform adapters and the credential provider

Status: Accepted (Overseer) - 2026-11-10, at the completion of F-06.2 (`f6e82bc`) and F-06.3 (`437a578`, `c3e9c0f`, `28b7d0b`; the Windows real-store cross-read run once under Owner action OA-10, [evidence](../evidence/OA-10-OA-11-owner-acts-2026-11-10.md)), as the Architect's draft of 2026-11-07 set. The Linux and macOS realizations are accepted only at F-06.4 and F-06.5, each on its own evidence.

Gate: architecture consultation after F-06.1 and S-01.2.2. Gate C (several supervision and credential structures), gate F (one contract across the Gitea host, the credential consumers and three platforms), and gate G for credential custody.

Supersedes: none. It refines decision 0007 (credential custody gains its provider adapters) and decision 0009 (the managed root gains service run, readiness and transition records). F-06.1 remains the Windows realization.

## Context
The Owner's directives of 2026-11-07 require:
- cross-platform installation and operation;
- a common lifecycle contract with platform adapters;
- an automated credential lifecycle on Windows, Linux and macOS through platform credential providers;
- zero routine administration.

F-06.1 and S-01.2.2 realize the lifecycle on Windows only. `gitea_host.py` already isolates its platform code and reaches credentials through one `CredentialProvider`. keyring 25.7.0 and its dependencies are already pinned, as are the Linux Gitea assets. The blueprint names the per-OS credential stores (`#platforms`) and states SHIP-01's cross-platform logical contract.

## Decision
1. **One contract, three adapters.** These are platform-neutral Python:
   - the lifecycle verbs: install, up, down, restart, status, inspect, verify; provision, rotate and retire credentials; upgrade, recover, uninstall;
   - their result shapes: `aieh-platform/1`, `aieh-asset/1`, `aieh-service-run/1`, `aieh-readiness/1`, `aieh-service-transition/1`;
   - their refusal codes.

   An adapter supplies only: supervised start and stop and environment liveness, process identity, listeners, user identity, the verified-bytes guarantee level, and the credential provider. No PowerShell, Windows path form, Job Object, Credential Manager, `/proc` or `launchctl` appears in the contract.
2. **The managed environment is OS-held.**
   - Windows: the harness supervisor in a kill-on-close Job Object (F-06.1).
   - Linux: a `systemd --user` transient service. The `PR_SET_PDEATHSIG` process-group supervisor is a disclosed fallback, enabled only by configuration.
   - macOS: a launchd job bootstrapped into the gui domain from a plist under the managed root, never from LaunchAgents.

   Each adapter reports its mechanism and how "the managed environment shuts down" maps onto it: explicit stop, user logout, and the mechanism's own limit.
3. **Credential provider.** The harness's `CredentialProvider` (get, set, delete, exists) is the contract.
   - Windows keeps the Credential Manager ctypes provider.
   - macOS and Linux use Python keyring 25.7.0 (MIT), pinned and hash-locked in the tools lock, with the backend instantiated explicitly (macOS Keychain; Secret Service) and its viability checked.
   - keyring's automatic backend selection, its configuration file, `PYTHON_KEYRING_BACKEND`, its command line and keyrings.alt are never used.
   - With no viable provider, the harness refuses and names the Owner act. No file-based or plaintext store exists.
4. **Credential invariants I1-I8 bind every platform:**
   1. A secret is never printed, logged, put on a command line or put in an environment variable.
   2. Each credential has one named entry.
   3. A secret is stored before the upstream change.
   4. Every act can be rerun and resumes.
   5. The harness fails closed.
   6. The backend is chosen by the harness.
   7. A no-exposure scan follows every act.
   8. Reports carry fingerprints only.
5. **Inspection.** Loopback-only binding, port ownership and non-elevation are verified from the kernel's own tables and process records: the Windows TCP table and token, `/proc`, `lsof` and `ps`. psutil is not adopted.
6. **Upgrade, recovery and uninstall.**
   - Assets sit side by side, and desired, staged and running versions are kept distinct.
   - A transition record is written before any process is replaced.
   - Rollback goes only to the transition backup. It is automatic before the new version is verified, and an Owner decision after.
   - Recovery reconciles the actual state before any retry.
   - Uninstall deletes nothing under `persistent/` and no asset.
7. **Platform status.** A platform is supported only with its own evidence record and its rows in the verification table. Windows is verified. Linux and macOS are designed and not yet verified until F-06.4 and F-06.5.

## Consequences
- F-06.2 extracts the contract and the Windows adapter without changing behaviour; F-06.1's evidence stands.
- F-06.3 adopts keyring for POSIX behind the contract. The basic tier stays stdlib-only, and the Gitea lifecycle on POSIX runs under the tools venv.
- F-06.4 and F-06.5 realize and verify Linux and macOS on real hosts. Each needs an Owner-provided host.
- F-06.6 realizes the transition record; R-02.3.x builds on it.
- Recorded limits:
  - the started-bytes guarantee is Windows-only (Linux re-hashes `/proc/<pid>/exe` after start; macOS re-hashes the path and inode);
  - the Linux fallback covers only the direct child;
  - headless Linux custody is undecided;
  - macOS Keychain behaviour over SSH, and Gatekeeper on the unsigned Gitea binary, are unverified;
  - settled at F-06.3: keyring 25.7.0's `macOS.Keyring` cannot look an entry up by name alone, so the factory refuses it; F-06.5 needs a decision on entry lookup.

## Owner confirmation
Pending:
1. Headless Linux credential custody.
2. The Linux verification host.
3. The macOS host, and the Gatekeeper posture.

Accepted by the Overseer: keyring kept off the Windows provider (installed in the tools set on every platform, never the Windows provider), and the POSIX lifecycle under the tools venv.

## Evidence
- The Owner directives of 2026-11-07.
- Decisions 0005, 0007, 0009 and 0010.
- `evidence/F-06.1-gitea-loopback.md` and `evidence/S-01.2.2-segregated-credentials.md`.
- `composition/lock/python/*.txt` (keyring 25.7.0 and its dependencies) and `composition/lock/components.lock.json` (the Gitea release assets).
- Blueprint `#platforms` and `#practical-workflows`.
- Upstream documentation read on 2026-11-07: PyPI keyring 25.7.0, the keyring v25.7.0 sources, systemd-run and user@.service, launchd.plist and launchctl, PR_SET_PDEATHSIG, the Gitea v28.3.0 release.
- The Architect's consultation of 2026-11-07.
