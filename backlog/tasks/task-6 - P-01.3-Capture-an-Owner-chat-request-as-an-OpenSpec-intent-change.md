---
id: TASK-6
title: 'P-01.3: Capture an Owner chat request as an OpenSpec intent change'
status: To Do
assignee: []
created_date: '2026-11-16T03:43:00Z'
labels: []
milestone: m-0
dependencies:
  - TASK-4
references:
  - >-
    AI_Engineering_Implementation_Project_Plan_Overseer_Prompts_2026-10-31.json#P-01.3
ordinal: 6000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Plan contract: leaf P-01.3 of AI_Engineering_Implementation_Project_Plan_Overseer_Prompts_2026-10-31.json (work_packages). The plan keeps the acceptance contract; the acceptance criteria below are its proof, checked equal to it by tools/plan_commitment.py. Committed by Commitment: I1 (evidence/bootstrap-log.md#commitment-i1-2026-11-16).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 One message yields exactly one intent change, idempotent by message id, and a retry or reconnect creates no second change; the Original Quote's span verifies against the stored message; the change passes tools/check_intent_record.py; the statement-to-objective originates edge resolves to the message; a request whose bytes differ from the stored message is refused with a stable code and changes nothing; no model is called; a method the Owner marks as a suggestion is recorded as a hypothesis, never as the objective.
<!-- AC:END -->
