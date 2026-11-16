---
id: TASK-4
title: 'U-02.1: Persist canonical Owner thread/message identities'
status: To Do
assignee: []
created_date: '2026-11-16T03:43:00Z'
labels: []
milestone: m-0
dependencies:
  - TASK-3
references:
  - >-
    AI_Engineering_Implementation_Project_Plan_Overseer_Prompts_2026-10-31.json#U-02.1
ordinal: 4000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Plan contract: leaf U-02.1 of AI_Engineering_Implementation_Project_Plan_Overseer_Prompts_2026-10-31.json (work_packages). The plan keeps the acceptance contract; the acceptance criteria below are its proof, checked equal to it by tools/plan_commitment.py. Committed by Commitment: I1 (evidence/bootstrap-log.md#commitment-i1-2026-11-16).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Reload returns exact messages in order without duplicate IDs.
- [ ] #2 Quotes are filled mechanically from the durable source (Overseer decision D2); a quote that differs from its source span is a failure.
<!-- AC:END -->
