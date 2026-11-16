---
id: TASK-12
title: 'E-01.5: Gate dispatch by observed isolation and source identity'
status: To Do
assignee: []
created_date: '2026-11-16T03:43:00Z'
labels: []
milestone: m-0
dependencies:
  - TASK-11
references:
  - >-
    AI_Engineering_Implementation_Project_Plan_Overseer_Prompts_2026-10-31.json#E-01.5
ordinal: 12000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Plan contract: leaf E-01.5 of AI_Engineering_Implementation_Project_Plan_Overseer_Prompts_2026-10-31.json (work_packages). The plan keeps the acceptance contract; the acceptance criteria below are its proof, checked equal to it by tools/plan_commitment.py. Committed by Commitment: I1 (evidence/bootstrap-log.md#commitment-i1-2026-11-16).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 No unauthorized workspace path or local-runtime fallback is reported as an accepted attempt; original parent proof remains satisfied.
- [ ] #2 Per attempt, the gate compares an independent docker inspect's caps, image ID and mounts with the admitted ones, and its NetworkMode and ExtraHosts with the recorded limit values of fd-container-network-deviations; any other value, or an inspect it cannot obtain, marks the attempt not launched: shown offline over inspect documents taken from recorded live observations (F-04.2; the D1 run record of 2026-11-16, steps (3) and (5b)), each cited, and over an altered copy for each compared field.
- [ ] #3 Execution non-overlap (review finding 1): no ordinal N+1 is reserved or dispatched for a Work, design revision and stage while ordinal N's conversation is executing as the Agent Server reports it, and an unknown execution state also refuses; acceptance tests prove both refusals.
- [ ] #4 The lineage attempt resolver resolves the dispatched attempt, against the Agent Server fake with its authority mode stated; against a live server, E-01.6's.
<!-- AC:END -->
