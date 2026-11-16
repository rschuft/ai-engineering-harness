---
id: TASK-9
title: 'E-01.7: Serve a deterministic Agent Server fixture on host loopback'
status: To Do
assignee: []
created_date: '2026-11-16T03:53:00Z'
labels: []
milestone: m-0
dependencies: []
references:
  - >-
    AI_Engineering_Implementation_Project_Plan_Overseer_Prompts_2026-10-31.json#E-01.7
ordinal: 9000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Plan contract: leaf E-01.7 of AI_Engineering_Implementation_Project_Plan_Overseer_Prompts_2026-10-31.json (work_packages), "Serve a deterministic Agent Server fixture on host loopback". The plan keeps the acceptance contract, and the reference to it is the authoritative link; the title is the plan title, cut at a word boundary only where its file path would exceed 100 characters. The acceptance criteria below are its proof, checked equal to it by tools/plan_commitment.py. Committed by Commitment: I1 (evidence/bootstrap-log.md#commitment-i1-2026-11-16).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Every route served is in the locked OpenAPI and each response validates against its schema; each scripted answer cites the recorded observation it reproduces, and an answer without one is a failure; the fixture binds 127.0.0.1 only; the production dispatcher and Agent Canvas code paths run against it unmodified, with no fixture-only branch in either; every record it causes carries authority mode fixture, and a test shows it can never be recorded as a live attempt.
<!-- AC:END -->
