# 0017 - Git-host agnosticism and Owner-scoped external publication

Status: Accepted (Owner) - 2026-11-10. An Owner direction, verbatim in `evidence/bootstrap-log.md` (Decisions,
"Owner decisions on OA-05, OA-14 and OA-15, plus an architectural correction on external collaboration"),
recorded as a decision by the Overseer. Where an earlier record or plan text disagrees, this record governs and
the other is the defect.

## Context
The Owner-action queue carried three upstream reports (OA-02 to OpenHands, OA-03 a private vulnerability report
to OpenHands, OA-09 to Dulwich) whose filing the Owner had authorized. The session had no authenticated GitHub
tool, so they stayed "Needs Owner now" and surfaced in every report. Filing them would have required a GitHub
CLI or credential: a hosting provider's tooling becoming a de facto prerequisite of engineering work.

## Decision
1. **Git is the foundation; the host is a choice.** The harness is Git-host-agnostic. Local Gitea is the selected
   governance service. GitHub, GitLab, Bitbucket, Azure DevOps and other hosting services are optional
   integrations. No hosting provider's authentication, API, CLI or issue tracker is a prerequisite for operating
   the engineering system.
2. **No autonomous publication to third-party projects.** Finding an upstream defect authorizes no issue,
   comment, pull request, discussion or private vulnerability report in the upstream project. External
   publication needs a new, explicit, scoped Owner decision naming the destination and the exact proposed
   content. Authorization is never inferred from an engineering task or an earlier general approval.
3. **Findings are internal knowledge.** Prepared findings, reproduction evidence, affected versions and upstream
   references are kept in the repository's evidence. They are deferred, optional external reporting: they do
   not block engineering and are not presented as outstanding Owner actions.
4. **Withdrawn authority.** The unexercised publication authority for OA-02, OA-03 and OA-09 is revoked
   (2026-11-10). The earlier authorizations stay recorded as history.
5. **No workaround.** No GitHub CLI is installed, no GitHub credential is accessed, no external connector is
   used and no provider-specific publishing workflow is built to resolve a finding.
6. **Ordinary Git stays.** Ordinary authorized Git operations against repositories the user owns or configures
   (for example this repository's checkpoint pushes) are unaffected.
7. **Optional and provider-neutral.** Any external contribution capability is optional, provider-neutral at the
   semantic boundary and separate from the core engineering lifecycle.

## Consequences
- OA-02, OA-03 and OA-09 move to the queue's Resolved table as "publication authority withdrawn, unexercised";
  their evidence files are unchanged.
- Overseer reports stop listing them.
- Detected, not yet examined: whether any plan leaf, document or tool makes a hosting provider a prerequisite
  of operating the system (as opposed to of publishing this repository). The Overseer schedules a bounded
  read-only audit; any finding is reconciled by the integrity process.

## Evidence
- The Owner direction of 2026-11-10 (bootstrap log, Decisions).
- `evidence/E-01.4.3-start-race.md` section 13 (OA-02), `evidence/OA-03-openhands-resume-report.md` (OA-03),
  `evidence/F-10.6-transports.md` "Upstream report: Dulwich `extra_headers`" (OA-09).
