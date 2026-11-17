---
id: TASK-10
title: 'U-01.2: Wire outcome navigation to engineering detail'
status: To Do
assignee: []
created_date: '2026-11-16T03:53:00Z'
updated_date: '2026-11-17T17:06:00Z'
labels: []
milestone: m-0
dependencies:
  - TASK-9
references:
  - >-
    AI_Engineering_Implementation_Project_Plan_Overseer_Prompts_2026-10-31.json#U-01.2
ordinal: 10000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Plan contract: leaf U-01.2 of AI_Engineering_Implementation_Project_Plan_Overseer_Prompts_2026-10-31.json (work_packages), "Wire outcome navigation to engineering detail". The plan keeps the acceptance contract, and the reference to it is the authoritative link; the title is the plan title, cut at a word boundary only where its file path would exceed 100 characters. The acceptance criteria below are its proof, checked equal to it by tools/plan_commitment.py. Committed by Commitment: I1 (evidence/bootstrap-log.md#commitment-i1-2026-11-16).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Owner reaches session detail from its outcome without interpreting internal IDs; original U-01 proof satisfied.
- [ ] #2 The Canvas session-selection fallback (UI-01) works, with rendering observed in a real browser, not only in jsdom.
- [ ] #3 Against the deterministic Agent Server fixture (E-01.7), labelled a fixture; the same against a live conversation through the dispatcher-issued forward is U-03.1's and U-03.2's.
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Disposed of by planning (2026-11-16): PB-2 by the plan amendment of 2026-11-16 (I1 blockers): E-01.7's UI face may serve source-derived fields where nothing is observed, marked; their observed counterpart is U-03.2's. PB-6 is recorded in this leaf's plan notes. Criteria unchanged; no blocker remains for planning. See evidence/bootstrap-log.md#i1-blockers-disposed-2026-11-16

Blocked (2026-11-17, engineering manager): gate G5 STOP, twice. (1) The pinned standalone Canvas fetches its MCP-catalog logos from cdn.simpleicons.org; 14 such public-image requests left loopback in the first G5 run (no credential), and every later run blocks them at the browser. Preventing them needs a content-security policy in the derived index.html, which planning's reading (log, i1-blockers-disposed-2026-11-16: the copy differs only by its two removed font imports) does not admit; an approved egress origin would be the Owner's (decision 0018 point 4.7). (2) Canvas's analytics-consent onboarding can be dismissed only by PATCH /api/settings, which the read-only UI face refuses, and planning's reading says telemetry is disabled only by an upstream setting. Both questions are carried to planning. Evidence: apps/owner-host/README.md (G5) at 2fb2e9b.
<!-- SECTION:NOTES:END -->
