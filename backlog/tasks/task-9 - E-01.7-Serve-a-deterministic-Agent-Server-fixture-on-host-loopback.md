---
id: TASK-9
title: 'E-01.7: Serve a deterministic Agent Server fixture on host loopback'
status: To Do
assignee: []
created_date: '2026-11-16T03:53:00Z'
updated_date: '2026-11-16T15:53:00Z'
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
- [ ] #1 The fixture has two faces: the dispatcher's, and the UI face, a read-only face that only the Owner UI and Agent Canvas call; the dispatcher never calls the UI face, and no value it serves reaches a record of the dispatch path.
- [ ] #2 Every route served, matched by method and path template with the UI face's path prefix removed, is in the locked OpenAPI or in the pinned route inventory of the profile D1 ran (profiles/strong-windows-qemu-whpx/agent-server/routes.json at sha256 919d67e2ee49823d0b4d0034f92ab190d95a64abfd9e07bb698680f9edabbc09, profile b7c5d2fedb6495679d6d24eca7df652b4f55e8832f2c17987c26569861eed9c7), with that route's recorded source named; a route in neither is a failure.
- [ ] #3 Each response validates against the locked OpenAPI's schema where that document defines the route for the runtime of the face that serves it, and otherwise against the response model of the pinned upstream source that serves the route at the locked release, named in the provenance table; each observed field is also checked against its citation.
- [ ] #4 In every scenario, each field of each scripted answer is, in the provenance table, one of: a recorded observation it reproduces, cited, and cited only when the inputs that determine it equal the observed request's (the result's test output only for D1's test command); a value echoed from the request; a value derived by a rule pinned in an accepted decision, or in harness code outside the fixture that the production path itself runs, named (the finished result's commit by decision 0024 point 4.4's rule over D1's recorded file changes, D1's commit id being a citation only); or the fixture's label; a field derived only from the fixture's own code is a failure.
- [ ] #5 Only on the UI face, only for a field the committed evidence does not observe, and only in a conversation status a live run reaches without fault injection (idle, running, finished), may a value be derived from the pinned upstream source or the locked OpenAPI, marked source-derived, not observed, in the provenance table and in the answer's label header; any other field, on either face, is a failure, and a request outside the fixture's catalog, or one whose answer needs an observed field that no cited observation's determining inputs match, is refused with the fixture's label.
- [ ] #6 A scenario's transport events (a response withheld, a connection closed) are not answers and are listed with the scenario in the provenance table; the failed scenario reproduces a recorded failure (S-01.3.1's observed refusal of a create).
- [ ] #7 The fixture binds 127.0.0.1 only; the production dispatcher and Agent Canvas code paths run against it unmodified, with no fixture-only branch in either; every record it causes carries authority mode fixture, and a test shows it can never be recorded as a live attempt.
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Disposed of by planning (2026-11-16): PB-1, PB-2, PB-4 and PB-6, by the plan amendment of 2026-11-16 (I1 blockers): the proof, action and artifact are amended, and the criteria above are the amended proof. No blocker remains for planning. See evidence/bootstrap-log.md#i1-blockers-disposed-2026-11-16
<!-- SECTION:NOTES:END -->
