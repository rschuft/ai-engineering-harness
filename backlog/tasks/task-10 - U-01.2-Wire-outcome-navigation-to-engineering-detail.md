---
id: TASK-10
title: 'U-01.2: Wire outcome navigation to engineering detail'
status: To Do
assignee: []
created_date: '2026-11-16T03:53:00Z'
updated_date: '2026-11-17T21:30:00Z'
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
- [ ] #4 Canvas's analytics-consent dialog is answered in the browser: the fixture's UI face accepts PATCH /api/settings only to set misc_settings.app_preferences.user_consents_to_analytics to a boolean, in the request body Canvas sends from that dialog as recorded in the provenance table, and refuses with its label any other write; it holds that value in the fixture process's memory only, never persisted, forwarded or written to a record (its call log file names the request, never the value), a restarted fixture holding none; it never sets, defaults or infers the value, so a fixture holding none serves none; a later GET /api/settings returns the held value, marked in its label header and the provenance table as held by the fixture in memory, not an OpenHands server setting.
- [ ] #5 Every Canvas copy served carries the one content-security-policy element of the Canvas reading (E-01.7's notes) and otherwise differs from the pinned build only by the two removed font imports; in gate G5, with the preference unset, declined and accepted, each in a throwaway profile whose selection is a test input and never the Owner's preference, no request is sent to a host other than 127.0.0.1.
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Disposed of by planning (2026-11-16): PB-2 by the plan amendment of 2026-11-16 (I1 blockers): E-01.7's UI face may serve source-derived fields where nothing is observed, marked; their observed counterpart is U-03.2's. PB-6 is recorded in this leaf's plan notes. Criteria unchanged; no blocker remains for planning. See evidence/bootstrap-log.md#i1-blockers-disposed-2026-11-16

Disposed of by planning (2026-11-17): PB-14 and PB-15, by the plan amendment of 2026-11-17 (I1 final), on the Owner's direction of 2026-11-17. The derived Canvas copy carries one content-security-policy element (no egress origin is approved; cdn.simpleicons.org stays refused), and the fixture's UI face admits one write, the analytics-consent preference held in memory. Criteria #4 and #5 are added (the amended proof). The plan notes give the G5 rule-3 reading, the DNS observation before the next G5 run, G6 rule 6's re-observation, the logos (no deferral) and two record corrections. No blocker remains for planning. See evidence/bootstrap-log.md#i1-final-planning-2026-11-17
<!-- SECTION:NOTES:END -->
