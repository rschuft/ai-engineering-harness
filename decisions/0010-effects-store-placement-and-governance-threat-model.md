# 0010 - Effects store placement and the governance-scoped threat model

Status: Accepted (Owner) - 2026-11-07. The Owner decided it in answer to the Overseer's questions after an Architect re-evaluation of decision 0004 (gates A and G). The Overseer recorded it.

It refines decision 0004, points 2 and 3, Owner act A4 part (1), and Owner clarifications 1 and 3 as they bear on location and identity. It also refines decision 0009, points 6 and 11, on the effects root. 0004 and 0009 stay Accepted, and their text is unchanged. This record states what now governs where they differ.

Supersedes: none.

## Context
Decision 0004 placed the privileged effects store outside every user profile, at an Owner-designated root with no default (proposed `D:\aieh-effects-state`). It reasoned that a volume root denies same-account processes the right to rename a protected directory. It also preferred a separate executor identity at G-04.2.1. Decision 0009 kept `effects_root` as a registered external location with no default, refused it inside the managed data root, and left its placement to this re-evaluation.

The Owner challenged the premise that a drive-root location is a custody control. An Architect measured the host's ACLs and ran non-elevated experiments on 2026-11-07. The evidence is in the bootstrap log entry of that date.

**Measured on this host:**
- Parent `FILE_DELETE_CHILD` alone decides whether a same-account, non-elevated process can rename or delete a protected child directory through the native API (`NtOpenFile` with DELETE only).
- `D:\` and `C:\ProgramData` deny the Owner's non-elevated token that right. Every directory under the user profile grants it.
- Win32 directory rename and delete fail under every parent, because they also request SYNCHRONIZE. Those failures prove nothing.
- A non-elevated process cannot create a directory owned by Administrators or SYSTEM.
- An open handle inside a directory blocks renaming that directory and every ancestor.

The drive-root rationale was therefore partly supported. The parent chain, not "drive root", governs relocation. Protection against relocation never extended to reading, writing or forging, which the object DACL and owner checks already cover wherever the store sits.

## Decision
1. **Threat model, explicitly scoped.**
   - **In scope:** preventing accidental or convenient circumvention of the established authorization and execution workflows, and accountable execution. That covers agents and CI acting through their normal interfaces (the execution guest, decision 0003; role tokens, decision 0007; the authorized effects interface) and operators taking shortcuts.
   - **Out of scope** (unchanged from 0004): a malicious process already running with the Owner's full Windows account privileges, an elevated or administrator actor, and operating-system compromise.

   The effects store is governed operational state, not a separate security enclave.
2. **Location is not custody.** Custody consists of the store's integrity and fail-closed checks: the hash-chained journal, restore epochs and reconciliation (0004 points 5 to 7), and the owner, DACL and custody verification on every open where configured. These checks detect unauthorized changes. Directory placement is not presented as a security control, and detection is kept distinct from OS-enforced prevention: the record and the inventory state which is which.
3. **Placement.** The effects store lives at `<managed-data-root>/persistent/effects/`, resolved by the shared resolver (decision 0009) as a managed category with that default. It needs no privileged installation location, no elevated setup and no Owner-designated path. A `config.yml` override follows 0009's precedence.
4. **Interface.** Agents and services use the authorized effects interface and never modify the store directly. Protection against unauthorized actions through the normal agent and service interfaces is retained: the guest boundary, the mount policy, the role-token matrix, Owner-only authorization and the executor allowlist.
5. **Relocation exposure is reported, not refused.** The store's status reports which identities could relocate it, computed from the parent chain. Opening does not fail for that reason alone. Under this placement the Owner's own account can relocate it, and that is expected and disclosed.
6. **Executor (G-04.2.1).** The executor's code and configuration are managed under the managed data root (`persistent/installs/` or another appropriate managed location), with defaults; no separate protected location and no Owner-designated path is required. Before any privileged operation, the executor validates its identity, configuration, authorization and integrity, and fails closed when any check fails. That a same-account process could modify or relocate the installation is not, by itself, grounds for refusing to operate. Such changes are detected wherever the integrity checks can detect them.
7. **No separate identity solely for filesystem attacks.** No privileged installation location, elevated setup or separate service identity is introduced solely to prevent same-account filesystem attacks. This replaces 0004 clarification 3's preference for a Windows service identity for that purpose. If a concrete requirement other than same-account filesystem defence later needs a separate identity, it is decided then (0004 clarification 7).
8. **Evidence rule.** Negative tests that assert an OS-enforced denial use the native path or an equivalent that does not request SYNCHRONIZE. A Win32 rename or delete failure is not evidence.

## Consequences
- **F-07.2:**
  - add an `effects` managed category (default `persistent/effects/`) to the resolver;
  - change the effects store's location policy so that it accepts that managed location and drops the live-policy refusals that exist only for location as custody (`LOCATION_PROFILE_ROOT` and `LOCATION_MANAGED_ROOT` for this purpose);
  - keep its refusals of the repository, the guest-state roots and the integration store's own database location;
  - add the relocation-exposure report;
  - update `security/inventory.json` (`store-effects` location, `privileged-executor`, a prevention-versus-detection finding) and `decisions/0009`'s companion documentation.

  Existing tests that pin the old refusals change with the policy, with the change justified by this record.
- **Plan:** reconcile the wording of G-04.2.1 ("restricted executor account") and G-04.2.2 ("restricted file/API permissions") with points 3, 6 and 7 through the integrity-tracked plan process. Their proofs stand: agents and CI, acting through their interfaces, cannot invoke or impersonate the executor or read or mutate receipts.
- **Owner act A4** reduces to whatever the executor still requires that is not location custody; G-04.2.1 decides that.
- **Recorded limit:** host-side processes running as the Owner's account, including the bootstrap agents, can read and relocate the store's files. The integrity checks detect substitution and tampering where the journal and checks allow, but cannot prevent it. This is `fd-bootstrap-shared-identity`, now an explicit part of the scoped threat model rather than a temporary gap.

## Evidence
- The Owner's answers of 2026-11-07, recorded verbatim by the Overseer.
- The Architect re-evaluation of 2026-11-07: host ACL metadata of `D:\`, `%LOCALAPPDATA%`, `C:\ProgramData` and `C:\`, and non-elevated scratch experiments.
- Decisions 0003, 0004, 0007 and 0009.
- `integrations/effects/effects_store.py` and `effects_custody.py`.
