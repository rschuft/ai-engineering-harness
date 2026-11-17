---
id: TASK-9
title: 'E-01.7: Serve a deterministic Agent Server fixture on host loopback'
status: Done
assignee: []
created_date: '2026-11-16T03:53:00Z'
updated_date: '2026-11-17T07:13:00Z'
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
- [x] #1 The fixture has two faces: the dispatcher's, and the UI face, a read-only face that only the Owner UI and Agent Canvas call; the dispatcher never calls the UI face, and no value it serves reaches a record of the dispatch path.
- [x] #2 Every route served, matched by method and path template with the UI face's path prefix removed, is in the locked OpenAPI or in the pinned route inventory of the profile D1 ran (profiles/strong-windows-qemu-whpx/agent-server/routes.json at sha256 919d67e2ee49823d0b4d0034f92ab190d95a64abfd9e07bb698680f9edabbc09, profile b7c5d2fedb6495679d6d24eca7df652b4f55e8832f2c17987c26569861eed9c7), with that route's recorded source named; a route in neither is a failure.
- [x] #3 Each response validates against the locked OpenAPI's schema where that document defines the route for the runtime of the face that serves it, and otherwise against the response model of the pinned upstream source that serves the route at the locked release, named in the provenance table; each observed field is also checked against its citation.
- [x] #4 On the dispatcher's face, a property that the validating schema or response model requires is not served when no provenance class of this proof admits a value for it and the dispatch path does not read it; it is listed with its answer in the provenance table as not served, and its absence alone is not a validation failure, while every served field still validates against its property.
- [x] #5 In every scenario, each field of each scripted answer is, in the provenance table, one of: a recorded observation it reproduces, cited, and cited only when the inputs that determine it equal the observed request's (the result's test output only for D1's test command); a value echoed from the request; a value derived by a rule pinned in an accepted decision, or in harness code outside the fixture that the production path itself runs, named (the finished result's commit by decision 0024 point 4.4's rule over D1's recorded file changes, D1's commit id being a citation only); or the fixture's label; a field derived only from the fixture's own code is a failure.
- [x] #6 A clock-valued field (a creation, update or event time, an uptime or an idle time) is a recorded observation that reproduces its cited value unchanged, whatever the request's time, and is marked clock-valued.
- [x] #7 A test, recording at the answer boundary over the restart matrix and the dispatch suites, binds the fields the dispatch path reads to the catalog's fields marked read, and none of them is clock-valued or not served.
- [x] #8 Only on the UI face, only for a field the committed evidence does not observe, and only in a conversation status a live run reaches without fault injection (idle, running, finished), may a value be derived from the pinned upstream source or the locked OpenAPI, marked source-derived, not observed, in the provenance table and in the answer's label header; any other field, on either face, is a failure, and a request outside the fixture's catalog, or one whose answer needs an observed field that no cited observation's determining inputs match, other than a property listed not served under the dispatcher's-face clause above, is refused with the fixture's label.
- [x] #9 The fixture's catalog holds at most one dispatcher-face entry marked source-derived, and only the one E-01.4.2's proof admits (the fields the dispatch path reads of the event that records the dispatcher's own initial message); it is excepted from the UI-face-only rule above and answers only E-01.4.2's in-process restart matrix, and while it is marked source-derived this fixture's listener does not serve it and refuses, with its label, the request that would need it.
- [x] #10 A scenario's transport events (a response withheld, a connection closed) are not answers and are listed with the scenario in the provenance table; the failed scenario reproduces a recorded failure (S-01.3.1's observed refusal of a create).
- [x] #11 The fixture binds 127.0.0.1 only; the production dispatcher and Agent Canvas code paths run against it unmodified, with no fixture-only branch in either; every record it causes carries authority mode fixture, and a test shows it can never be recorded as a live attempt.
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Disposed of by planning (2026-11-16): PB-1, PB-2, PB-4 and PB-6, by the plan amendment of 2026-11-16 (I1 blockers): the proof, action and artifact are amended, and the criteria above are the amended proof. No blocker remains for planning. See evidence/bootstrap-log.md#i1-blockers-disposed-2026-11-16

Amended again by planning (2026-11-16), on PB-12 and the rules PB-10 shares with E-01.4.2, by the plan amendment of 2026-11-16 (I1 recovery): the proof and action are amended, and the criteria above are the amended proof. No blocker remains for planning. See evidence/bootstrap-log.md#i1-recovery-disposed-2026-11-16
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
PASS by the engineering manager's verdict, evidence/bootstrap-log.md#e-01-7-verdict-2026-11-16. Commits e09c639..358600e. Criterion 11's records clause is proved with E-01.8 criterion 1 (design R11); Agent Canvas running against the UI face is G5 at U-01.2.
<!-- SECTION:FINAL_SUMMARY:END -->
