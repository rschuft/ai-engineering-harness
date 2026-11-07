# 0004 - Privileged effect store: custody and restore semantics

Status: Proposed (Overseer, accepting option O4 of an Architect consultation) -
2026-11-06. The Owner's acknowledgement is pending.
F-05.2 proceeds on fixtures under this Proposed decision, because it creates nothing
live or irreversible. Acceptance needs the Owner's acknowledgement of the custody
direction and of the recorded limit: host-side bootstrap agents run as the Owner's
account, and UAC consent, not an OS security boundary, gates their elevation.
Gate: architecture consultation before F-05.2, gate G (custody boundary of the
privileged effect journal).
Supersedes: none.

## Context
Blueprint `#infrastructure-state` keeps two kinds of local state apart:
- the Integration Service's trusted-host store, `integration.sqlite` (F-05.1), which
  holds coordination receipts and rebuildable projections;
- the privileged external-effect journal, `effects.sqlite`, whose receipts the
  protected executor keeps itself ("Protected executor keeps its own effect
  receipts"; "No agent-write access"; SEC-02).

F-05.2 must provide the effect store, and backup and restore for both stores, before any
executor exists.

**Threat model** (from the blueprint):
- **T1:** untrusted agents and CI must not read, write or forge receipts, and must not
  invoke the executor.
- **T2:** the Integration Service, which is exposed to agent traffic, must not be able
  to write effect receipts.
- **T3:** the executor itself runs with least privilege (G-04.2.1).
- Not a target: the Owner as administrator, or a compromised OS.

**Host facts**, from non-elevated, read-only probes:
- the agent's token is Medium integrity;
- `Administrators` is deny-only in that token;
- the token holds no SeTakeOwnership, SeBackup or SeRestore privilege;
- UAC is on (`EnableLUA=1`, `ConsentPromptBehaviorAdmin=5`, secure desktop).

**Options:**
- **O1, a dedicated executor account now.** This is the target state, but it belongs to
  G-04.2.1, which selects the executor runtime. Not now.
- **O2, the Owner's account with an A3-style ACL.** Rejected. The Owner's SID, as the
  owner, keeps WRITE_DAC, which defeats T2.
- **O3, DPAPI, signing, integrity levels or AppContainer as custody.** Rejected as
  custody. A keyless hash chain over the append-only events is kept, as tamper evidence
  and as the backup high-water marker.
- **O4, elevation-gated custody now, the executor principal later.** Accepted.

## Decision
1. **Two stores, two custodies.** `effects.sqlite` is a separate database with its own
   directory, migration line, `PRAGMA application_id`, backup line and owner identity.
   It is never attached to, co-located with, or backed up with `integration.sqlite`.
   Nothing with an agent-callable surface writes it.
2. **Custody identity on this host class.**
   - **Target:** a dedicated executor principal with its own SID and least privilege,
     provisioned by Owner act A4 at G-04.2.1. Its kind is decided with the executor
     runtime. `runas /savecred`, and any executor credential in the Owner's Credential
     Manager, are forbidden.
   - **Interim: elevation-gated custody.** An elevated Owner act creates the root. Its
     owner is `BUILTIN\Administrators`, inheritance is removed, and the DACL holds only
     SYSTEM and Administrators. The executor principal is later added as one Modify
     entry. There is no entry for the Owner's interactive account, Users, Authenticated
     Users or Everyone.
   - The store verifies this template on every open and refuses otherwise.
3. **Location.** An explicit path, with no default, on a local fixed volume. It is
   outside the repository, every user profile (including `%LOCALAPPDATA%`), every
   guest-state root, and the integration store's tree. The Owner designates the root
   (proposed: `D:\aieh-effects-state`). `init` never creates the root.
4. **No live store before its first consumer.** F-05.2 proves the mechanisms on
   fixtures. The live store is created only by A4 at G-04.2.1. G-04.2.2 provisions the
   F-05.2 store on that root, proves denied access on it, and creates no second schema.
5. **Backup.** Only the SQLite backup mechanism, run by each store's owner identity, into
   `backups/` under the same custody. A backup counts only once verified: an integrity
   check and a sha256 manifest recording the canonical high-water mark and the chain
   head. Never a copy of live files. Local disk only. Canonical receipts are never
   deleted.
6. **Restore.** An act of the store's owner identity: for the effect store, elevated,
   with the executor stopped. It needs a verified backup and exclusive custody.
   - The previous live content is preserved aside, never discarded.
   - A rollback is refused unless explicitly accepted.
   - Projections are dropped and rebuilt.
   - A restore epoch is appended, marked `reconciliation_required`. New reservations are
     refused while it is open.
7. **Restore semantics.** A restore loses knowledge, never effects. The absence of a
   receipt after a restore is not evidence that an effect did not happen.
   - Before any effect, the one-time effect key is re-derived from the recorded inputs
     and checked against the observed target.
   - Performed: recorded as `observed`, never reissued.
   - Indeterminate: stays `unknown`, and the process stops. Only a recorded Owner
     attestation resolves it.
8. **Projections** are rebuilt from canonical sources, under an authorizer that denies
   writes outside the projection. Until OpenSpec and Backlog.md are adopted, a
   file-based synthetic repository stands in for them, and that limit is recorded.
9. **Recorded limits.**
   - Host-side bootstrap agents run as the Owner's account. Their elevation is gated by
     UAC consent, which is not an OS security boundary. So no engineering agent runs
     elevated, and the Owner performs acts on the effect store in the Owner's own
     elevated window.
   - `integration.sqlite` stays in Owner-session custody during bootstrap.
   - The guest boundary (decision 0003) is the boundary against untrusted agents.
   - OS-crash durability is unverified on this host.

## Consequences
- **G-04.2.2** provisions and proves the F-05.2 store. It creates no second effects
  schema.
- **F-05.2** proves on fixtures only:
  - It creates no live root, account, elevated process, scheduled task, service or
    network listener.
  - Its recorded limits:
    - a fixture oracle stands in for the observed target;
    - a fixture repository stands in for OpenSpec and Backlog.md;
    - OS-crash durability is UNKNOWN;
    - live identity separation cannot be proven before G-04.2.1 and G-04.2.2.
- **Owner act A4** is requested at G-04.2.1, not now. Its wording:

  > A4, in two parts, each approved separately: (1) Designate an effects-state root on
  > a local fixed NTFS volume outside your profile, the repository and the guest-state
  > root (proposed `D:\aieh-effects-state`). From a PowerShell window you open with Run
  > as administrator, create it, remove inherited permissions, and grant full control
  > to `NT AUTHORITY\SYSTEM` and `BUILTIN\Administrators` only - no entry for your own
  > account. (2) Create the executor principal that G-04.2.1 selects (a Windows service
  > under a virtual service account, or a local account without interactive logon
  > whose password only the Task Scheduler holds), and grant it Modify on that root.
  > Never store its credential in your Credential Manager and never use
  > `runas /savecred`. Afterwards, restores of the effects store are your elevated act,
  > with the executor stopped.
- **Carried items:**
  - G-04.4.2 and G-04.5 replace the fixture oracle with real target probes.
  - E-01.4.x reconciles the integration store against OpenHands.
  - Custody of the integration store moves to the Integration Service identity in the
    Integration Service leaves.

## Current facts (2026-11-06, F-05.2 gate G)
- Nothing live exists for the effect store: no effects root, executor principal,
  elevated process, scheduled task or service has been created.
- The integration store's default path is under `%LOCALAPPDATA%`
  (`integrations/store/README.md`), which matches the Owner-session custody of point 9.

## Evidence
- **Consultation:** the Architect's gate-G consultation for F-05.2 (2026-11-06), with its
  threat model, options and draft decision; the Overseer accepted option O4 and its
  builder constraints.
- **Blueprint:** `#infrastructure-state` and SEC-02, as cited by that consultation.
- **Host probes, 2026-11-06:** non-elevated and read-only. They read the agent token's
  integrity level, group attributes and privileges, and the UAC policy values.
- **Records:** decision 0003 (guest boundary and the A3 guest-state root); F-05.1
  (`integrations/store/README.md`).
