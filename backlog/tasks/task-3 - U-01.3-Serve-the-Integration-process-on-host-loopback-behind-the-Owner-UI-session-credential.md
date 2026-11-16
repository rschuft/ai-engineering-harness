---
id: TASK-3
title: >-
  U-01.3: Serve the Integration process on host loopback behind the Owner UI
  session credential
status: To Do
assignee: []
created_date: '2026-11-16T03:43:00Z'
labels: []
milestone: m-0
dependencies: []
references:
  - >-
    AI_Engineering_Implementation_Project_Plan_Overseer_Prompts_2026-10-31.json#U-01.3
ordinal: 3000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Plan contract: leaf U-01.3 of AI_Engineering_Implementation_Project_Plan_Overseer_Prompts_2026-10-31.json (work_packages). The plan keeps the acceptance contract; the acceptance criteria below are its proof, checked equal to it by tools/plan_commitment.py. Committed by Commitment: I1 (evidence/bootstrap-log.md#commitment-i1-2026-11-16).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Edge nm-owner-ui-integration's enforcement is observed: the process binds 127.0.0.1 only (host census), every request needs the Owner UI session credential, and that credential is not shaped like an Agent Server key; the Integration process's Owner login and the UI session credential are built, and a missing or foreign credential is refused, as is an expired one, each with a stable code and changing nothing; no management key, bot token, the session credential itself, or any other Owner or provider credential is present in the process's environment, configuration or logs.
<!-- AC:END -->
