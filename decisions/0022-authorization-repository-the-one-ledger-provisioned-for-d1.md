# 0022 - The authorization repository: the one ledger of real Owner authorizations, provisioned for D1

Status: Accepted (product manager) - 2026-11-13, under decision 0018 points 1 and 3.1 (it changes the contract between leaves: a new leaf E-05.7 carved from G-03.1, and S-03.3's dependency on it). It authorizes no reserved act: creating the repository, the collaborations it grants and its first verification are Owner act OA-30, presented separately; every authorization recorded in it stays the Owner's per act. Previously: proposed by the architect at a consultation of 2026-11-13 (gates G and F), weighed by the product manager and challenged by the program manager.

**Authority:** decision 0012 (the authorization channel: the recorder, its single-use challenge, the protected merge, the fail-closed protection check of point 6 and OA-16); decision 0018 points 1, 3, 4.3, 4.4, 4.7 and 4.8; decision 0021 (the provider-envelope receipt the broker's start checks; its point 9.2 left the first real envelope's repository open); decision 0020 (dispatch-input decisions are integration-store receipts, not merges); the blueprint's "Authorization repository contract" (`#authorization-qualification`: a dedicated repository and one authorization branch); the planned asset `repo-gitea-authorization` in `security/inventory.json`.

**Gate:** architecture consultation at gates G (the custody of durable authorization records) and F (the authorization repository is G-03.1's, outside D1's committed set).

**Supersedes:** none. It settles decision 0021 point 9.2 and the S-03.5 verdict's finding 2, and applies decision 0012 without changing its text.

## Context

D1's real-provider step (S-03.3 step 6b, then E-05.5's model calls) needs the Owner's provider-envelope authorization recorded by the authorization recorder as a protected merge (decision 0021). The managed recorder admits one repository only, the S-01.2.2 authorization fixture (`authorization_recorder.admitted_policies`), because the authorization repository of G-03.1 is not built, and G-03.1 lies far outside D1.

Premise corrected at the consultation (observed): D1's other recorder decisions do **not** need a Gitea repository. The design acceptance and the manifest promotions (P-04.3, `input_recorder.py`) and the model selection (S-03.5, `selection_recorder.py`) are integration-store receipts and import no Gitea module (decision 0020 points 4, 5 and 9). The merge path refuses any statement not attributed to the Owner (`STATEMENT_NOT_OWNER`), so it cannot carry a delegated decision. The only D1 record that needs the ledger is the Owner's `authorize-operation` of kind `provider-envelope`, at S-03.3 step 6b and whenever an envelope expires, is superseded or closes.

The fixture is defined by adversarial use: site-administrator drift injection (OA-16 Act D), bot-merge negative controls, the stale-head control, G-03.2's planned `sudo` probe, and the CI lane's planned proposals. It was created as a disposable fixture.

## Considered options

1. **Record D1's real authorizations in the fixture.** No new code, but each adversarial exercise becomes an act on the real ledger, a disposable repository silently changes class (decision 0018 point 4.4 protects only what was not created disposable), the Owner would be shown a spend and egress authorization as a merge into a fixture, and a merge-commit record cannot be moved later. Rejected. It is not a fallback inside delegation: it would need the Owner's explicit acceptance of the fixture as durable authorization custody (point 4.8).
2. **A dedicated authorization repository, provisioned now as a D1 leaf carved from G-03.1.** Chosen.
3. Rejected: a store-only Owner record without a merge (contradicts decision 0012 point 1, decision 0021 section 1 and S-03.5's passed proof); the demo repository (its content enters guests); a second repository inside the fixture's organization or the planned governance organization (the label; organization-level CI settings); moving the protection auditor off the fixture (loses the requalification surface).

## Decision

1. **One ledger.** The authorization repository is the harness's authorization repository, not a D1 repository. G-03.1 later completes its policy on the same repository: there is no second repository and no migration. Its name is permanent, in its own organization, and contains neither "fixture" nor "d1"; the engineering manager chooses it before OA-30 is presented.
2. **Admission.** The managed recorder context admits exactly the authorization repository. The fixture stays admitted only in exercise contexts, which carry their own state and store. Every `owner-authorization/v1/` receipt in the managed store is then a merge on the ledger. This matters because the envelope read side (`envelope_decisions.candidates`) has no repository predicate. A repository predicate on that read side becomes mandatory as soon as the managed recorder admits a second non-fixture repository.
3. **Declaration.** The repository carries the same total protection declaration as the qualified fixture, as its own declaration entry, so G-03.1 can change one without the other. The protection check of decision 0012 point 6 covers it as declared. G-03.1 keeps stale-approval dismissal, required checks, the audit configuration, the typed proposal convention and its whole proof.
4. **Proposal.** A deterministic proposal act opens the manifest's pull request with bot tokens only and reads back the blob's sha256, so the Owner is never asked about bytes that differ from the canonical manifest (`ENVELOPE_MISMATCH`).
5. **Fixtures stay fixtures.** No real effect is ever authorized on a fixture. Adversarial exercises (negative controls, drift injection, administrator probes) run only on fixtures, never on the ledger.
6. **Work.** New plan leaf E-05.7 (deps P-04.2 and S-01.2.2); S-03.3 and G-03.1 depend on it (the plan amendment of 2026-11-13). Its offline build needs no Owner act; its live half is OA-30.

## Consequences

- **Widening, presented as OA-30 (decision 0018 point 4.7):** the protection auditor `aieh-bot-protection-audit` becomes repository administrator of this repository as well, with its token and scope unchanged. The four bots gain the fixture's permissions there. `aieh-owner` gains merge on its protected branches. Its own per-act row, not an item of OA-22: OA-22 expires at D1's acceptance, and this repository is permanent.
- **Audit log:** decision 0012 point 8 lists Gitea's audit log as merge evidence, and its Owner confirmation 4 states audit logging is on. No tracked source configures `[audit]`, and it is not verified. For D1 the evidence of a merge is the recorder's receipt, its trailers and the read-back; the audit log corroborates only where present. G-03.1's action configures it. OA-30's presentation says so. Recorded as a Current-facts note on decision 0012.
- **Residual risks, disclosed:**
  - Same-account and channel limits are unchanged (decision 0010 point 1; decision 0012 points 9 and 13).
  - The administrator's `sudo` path stays detect-only.
  - The new repository's denials are inferred from declaration equality with the qualified fixture, not exercised there, by design. `fd-protection-check-toctou` applies to a real ledger.
  - In D1 one session drives both the proposing and reviewing bots; the control is the Owner's decision on the manifest shown and the broker's regeneration of the canonical manifest.
  - The builder's standing token can open proposals in the ledger; OA-22 (f) keeps attempts off it by judgment only.
  - The ledger's git data has no backup (the Gitea upgrade backup covers `gitea.db` and `app.ini`).
  - `block_on_outdated_branch` allows one open proposal at a time.
- **Records:** a Current-facts note on decision 0012 (this ledger and the audit-log status) and on decision 0021 (point 9.2 settled).

## Evidence

- The consultation of 2026-11-13: `evidence/bootstrap-log.md`, anchor `planning-pass-2026-11-13`.
- `integrations/owner/authorization_recorder.py` (`admitted_policies`, `managed_context`, the statement checks); `integrations/owner/envelope_decisions.py`; `integrations/owner/input_recorder.py`; `integrations/owner/selection_recorder.py`; `integrations/gitea/gitea_roles.py`; `integrations/gitea/protection_check.py`.
- OA-16 Acts A to E and OA-14's record phase (log Decisions, 2026-11-12): the protection check is qualified on the fixture only.

## Not verified

Anything live. That the managed store holds no recorder receipt today is inferred from the exercise's own-store design; E-05.7 checks it read-only on entry. Gitea facts are from this repository's records, not re-read at the upstream source.
